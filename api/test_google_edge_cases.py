"""Casos límite del acceso y el registro con Google que la cobertura marcaba sin probar."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import GoogleAccount
from .services import google_auth


class ConcurrentGoogleLinkingTests(TestCase):
    """`get_existing_user` cuando otra petición vincula la misma cuenta de Google a la vez."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("ada", email="ada@gmail.com")

    def test_the_account_linked_by_the_other_request_is_used(self):
        linked_elsewhere = GoogleAccount(user=self.user, google_sub="sub-ada")
        with (
            patch.object(google_auth, "_find_account", side_effect=[None, linked_elsewhere]),
            patch.object(GoogleAccount.objects, "create", side_effect=IntegrityError("google_sub duplicado")),
        ):
            user = google_auth.get_existing_user("ada@gmail.com", "sub-ada")

        self.assertEqual(user, self.user)

    def test_without_an_account_after_the_conflict_no_user_is_returned(self):
        GoogleAccount.objects.create(user=get_user_model().objects.create_user("otra"), google_sub="sub-otra")
        with (
            patch.object(google_auth, "_find_account", return_value=None),
            patch.object(GoogleAccount.objects, "create", side_effect=IntegrityError("google_sub duplicado")),
        ):
            self.assertIsNone(google_auth.get_existing_user("ada@gmail.com", "sub-ada"))

    def test_an_unknown_email_after_the_conflict_returns_no_user(self):
        conflict = IntegrityError("carrera")
        with patch.object(google_auth, "_find_account", side_effect=[conflict, None]):
            self.assertIsNone(google_auth.get_existing_user("nadie@gmail.com", "sub-nadie"))


GOOD_CLAIMS = {"sub": "sub-edge", "email": "edge@gmail.com", "email_verified": True, "given_name": "Edge"}


@override_settings(GOOGLE_CLIENT_ID="test-google-client")
class GoogleCredentialShapeTests(APITestCase):
    def post_with_claims(self, claims, url_name="google_login", data=None):
        with patch("api.services.google_auth.verify_credential", return_value=claims):
            return self.client.post(reverse(url_name), data or {"credential": "mock"}, format="json")

    def test_claims_that_are_not_an_object_are_rejected(self):
        for claims in (["sub", "email"], "texto", None):
            with self.subTest(claims=claims):
                response = self.post_with_claims(claims)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_missing_empty_or_too_long_sub_is_rejected(self):
        for sub in (None, "", 123, "x" * 256):
            with self.subTest(sub=sub):
                response = self.post_with_claims({**GOOD_CLAIMS, "sub": sub})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(GoogleAccount.objects.count(), 0)

    def test_a_body_that_is_not_an_object_is_rejected_on_login_and_register(self):
        for url_name in ("google_login", "google_register"):
            with self.subTest(url=url_name), patch("api.services.google_auth.verify_credential") as verifier:
                response = self.client.post(reverse(url_name), ["credential", "mock"], format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("objeto", str(response.data))
                verifier.assert_not_called()

    def test_a_username_taken_by_a_concurrent_registration_is_reported(self):
        with patch("api.views.create_google_user", side_effect=IntegrityError("username duplicado")):
            response = self.post_with_claims(
                GOOD_CLAIMS, url_name="google_register", data={"credential": "mock", "username": "EdgeUser"}
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"], {"username": ["Ese nombre de usuario no está disponible."]})
