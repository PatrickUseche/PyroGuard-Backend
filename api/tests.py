import logging

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APITestCase

from .exceptions import api_exception_handler
from .models import Node, SensorReading


class ReadingsContractTests(APITestCase):
    ingest_api_key = "test-ingest-key"

    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-001")

    def test_get_returns_flat_list_with_frontend_fields(self):
        SensorReading.objects.create(
            node=self.node,
            temperature=37.5,
            humidity=22.0,
            smoke=75,
            flame=False,
        )

        response = self.client.get(reverse("receive_reading"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            set(response.data[0]),
            {
                "node_id",
                "temperature",
                "humidity",
                "smoke",
                "flame",
                "timestamp",
            },
        )
        self.assertEqual(response.data[0]["node_id"], "NODE-001")

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_without_credentials_is_rejected(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(response.data["status"], "error")
        self.assertIn("errors", response.data)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_with_valid_api_key_creates_reading(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertEqual(response.data["status"], "success")
        self.assertNotIn(self.ingest_api_key, str(response.data))

    def test_authenticated_token_client_can_create_reading(self):
        user = get_user_model().objects.create_user(username="trusted-client")
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 1)

    def test_authenticated_session_client_can_create_reading(self):
        user = get_user_model().objects.create_user(username="session-client")
        self.client.force_login(user)

        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 1)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_with_invalid_api_key_is_rejected(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
            HTTP_X_API_KEY="invalid-key",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["status"], "error")
        self.assertNotIn("invalid-key", str(response.data))
        self.assertEqual(SensorReading.objects.count(), 0)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_with_valid_api_key_returns_uniform_validation_error(self):
        response = self.client.post(
            reverse("receive_reading"),
            {"node_id": self.node.node_id},
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("errors", response.data)
        self.assertIn("temperature", response.data["errors"])

    @override_settings(INGEST_API_KEY="")
    def test_post_is_rejected_when_ingest_key_is_not_configured(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(SensorReading.objects.count(), 0)

    def test_permission_errors_keep_uniform_shape(self):
        response = api_exception_handler(
            PermissionDenied("No autorizado."),
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("errors", response.data)

    def test_validation_errors_keep_uniform_shape(self):
        response = api_exception_handler(
            ValidationError({"field": ["Valor inválido."]}),
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("field", response.data["errors"])

    def test_unexpected_errors_return_safe_response_and_log_type(self):
        secret_detail = "private database credentials"
        with self.assertLogs("api.exceptions", level=logging.ERROR) as logs:
            response = api_exception_handler(
                RuntimeError(secret_detail),
                {},
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        self.assertEqual(
            response.data,
            {
                "status": "error",
                "errors": {"detail": "Error interno del servidor."},
            },
        )
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn(secret_detail, logs.output[0])

    def valid_payload(self):
        return {
            "node_id": self.node.node_id,
            "temperature": 37.5,
            "humidity": 22.0,
            "smoke": 75,
            "flame": False,
            "timestamp": "2026-10-06T18:30:00-05:00",
        }
