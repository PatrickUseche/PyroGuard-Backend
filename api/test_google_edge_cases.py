"""Casos límite del acceso y el registro con Google que la cobertura marcaba sin probar."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

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
