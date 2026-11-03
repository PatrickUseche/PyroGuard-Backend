"""Pruebas de GET /health/ con la base de datos y la IA caídas."""
from unittest.mock import MagicMock, patch

import requests
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status

from .services.health import check_ai, check_database, get_health


class DatabaseHealthTests(TestCase):
    def test_a_working_database_reports_ok_with_its_latency(self):
        result = check_database()

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["latency_ms"], 0)

    def test_a_failing_database_reports_down_without_details(self):
        with patch("api.services.health.connection") as connection:
            connection.cursor.side_effect = OperationalError("password=secreto host=db.interno")
            with self.assertLogs("api.health", level="ERROR") as logs:
                result = check_database()

        self.assertEqual(result, {"status": "down"})
        self.assertNotIn("secreto", " ".join(logs.output))


@override_settings(AI_SERVICE_URL="http://ia.test")
class AIHealthTests(TestCase):
    def test_a_reachable_ai_reports_ok(self):
        with patch("api.services.health.requests.get", return_value=MagicMock(status_code=200)) as get:
            result = check_ai()

        self.assertEqual(result["status"], "ok")
        self.assertIn("latency_ms", result)
        (url,), kwargs = get.call_args
        self.assertEqual(url, "http://ia.test/health")
        self.assertEqual(kwargs["timeout"], 2.0)

    def test_an_ai_that_does_not_connect_is_unavailable(self):
        with patch("api.services.health.requests.get", side_effect=requests.ConnectTimeout("caída")):
            with self.assertLogs("api.health", level="WARNING"):
                self.assertEqual(check_ai(), {"status": "unavailable"})

    def test_an_ai_that_answers_with_an_error_is_unavailable(self):
        for code in (500, 503, 404):
            with self.subTest(code=code):
                with patch("api.services.health.requests.get", return_value=MagicMock(status_code=code)):
                    with self.assertLogs("api.health", level="WARNING"):
                        self.assertEqual(check_ai(), {"status": "unavailable"})

    @override_settings(AI_SERVICE_URL="")
    def test_without_a_configured_ai_it_is_disabled_and_not_called(self):
        with patch("api.services.health.requests.get") as get:
            self.assertEqual(check_ai(), {"status": "disabled"})

        get.assert_not_called()


class HealthEndpointTests(TestCase):
    def get(self):
        return self.client.get(reverse("health"))

    @override_settings(AI_SERVICE_URL="")
    def test_everything_up_with_the_ai_disabled(self):
        response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")
        self.assertEqual(response.data["database"]["status"], "ok")
        self.assertEqual(response.data["ai"], {"status": "disabled"})

    @override_settings(AI_SERVICE_URL="http://ia.test")
    def test_everything_up_with_the_ai_answering(self):
        with patch("api.services.health.requests.get", return_value=MagicMock(status_code=200)):
            response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")
        self.assertEqual(response.data["ai"]["status"], "ok")

    @override_settings(AI_SERVICE_URL="http://ia.test")
    def test_a_down_ai_degrades_but_does_not_fail_the_backend(self):
        with patch("api.services.health.requests.get", side_effect=requests.ConnectionError("caída")):
            with self.assertLogs("api.health", level="WARNING"):
                response = self.get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "degraded")
        self.assertEqual(response.data["database"]["status"], "ok")
        self.assertEqual(response.data["ai"], {"status": "unavailable"})

    @override_settings(AI_SERVICE_URL="http://ia.test")
    def test_a_down_database_returns_503_and_skips_the_ai(self):
        with patch("api.services.health.connection") as connection:
            connection.cursor.side_effect = OperationalError("sin conexión")
            with patch("api.services.health.requests.get") as get:
                with self.assertLogs("api.health", level="ERROR"):
                    response = self.get()

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "down")
        self.assertEqual(response.data["database"], {"status": "down"})
        self.assertEqual(response.data["ai"], {"status": "not_checked"})
        get.assert_not_called()

    @override_settings(PUBLIC_READ_ACCESS=False, AI_SERVICE_URL="")
    def test_it_is_public_even_when_reads_are_private(self):
        self.assertEqual(self.get().status_code, status.HTTP_200_OK)

    @override_settings(AI_SERVICE_URL="")
    def test_it_ignores_an_invalid_token(self):
        response = self.client.get(reverse("health"), HTTP_AUTHORIZATION="Token invalido")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(AI_SERVICE_URL="")
    def test_it_is_not_rate_limited(self):
        codes = {self.get().status_code for _ in range(5)}

        self.assertEqual(codes, {status.HTTP_200_OK})

    def test_get_health_returns_the_body_and_the_status_code(self):
        with override_settings(AI_SERVICE_URL=""):
            body, code = get_health()

        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "ok")
