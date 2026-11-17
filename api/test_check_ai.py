"""Pruebas del comando `check_ai` con la IA simulada."""
from io import StringIO
from unittest.mock import MagicMock, patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

TARGET = "api.management.commands.check_ai.requests"
HEALTHY = {"status": "ok", "model_loaded": True, "model_version": "pyroguard-rf-1.1.0"}
PREDICTION = {"status": "ok", "contract_version": "1.1", "risk_level": "NORMAL"}


def response(status_code, body=None):
    mock = MagicMock(status_code=status_code)
    mock.json.return_value = body if body is not None else {}
    return mock


def run():
    out = StringIO()
    call_command("check_ai", stdout=out)
    return out.getvalue()


@override_settings(AI_SERVICE_URL="https://ia.test", AI_API_KEY="clave-secreta")
class CheckAICommandTests(SimpleTestCase):
    def test_a_healthy_ai_that_accepts_the_key_passes(self):
        with patch(TARGET) as http:
            http.get.return_value = response(200, HEALTHY)
            http.post.return_value = response(200, PREDICTION)
            output = run()

        self.assertIn("[OK] health: modelo pyroguard-rf-1.1.0", output)
        self.assertIn("[OK] predict: risk_level=NORMAL contrato 1.1", output)
        self.assertEqual(http.get.call_args.args, ("https://ia.test/health",))
        self.assertEqual(http.post.call_args.args, ("https://ia.test/predict",))
        self.assertEqual(http.post.call_args.kwargs["headers"], {"X-AI-API-Key": "clave-secreta"})

    def test_the_key_is_never_printed(self):
        with patch(TARGET) as http:
            http.get.return_value = response(200, HEALTHY)
            http.post.return_value = response(200, PREDICTION)
            output = run()

        self.assertIn("AI_API_KEY: configurada", output)
        self.assertNotIn("clave-secreta", output)

    def test_a_rejected_key_fails_with_a_hint(self):
        for code in (401, 403):
            with self.subTest(code=code), patch(TARGET) as http:
                http.get.return_value = response(200, HEALTHY)
                http.post.return_value = response(code)
                with self.assertRaisesMessage(CommandError, "AI_API_KEY debe ser igual"):
                    run()

    def test_an_unreachable_ai_fails(self):
        with patch(TARGET) as http:
            http.RequestException = requests.RequestException
            http.get.side_effect = requests.ConnectionError("sin red")
            http.post.side_effect = requests.ConnectionError("sin red")
            with self.assertRaisesMessage(CommandError, "health: sin respuesta (ConnectionError)"):
                run()

    def test_a_degraded_ai_fails(self):
        with patch(TARGET) as http:
            http.get.return_value = response(200, {"status": "degraded", "model_loaded": False})
            http.post.return_value = response(200, PREDICTION)
            with self.assertRaisesMessage(CommandError, "el modelo no está cargado"):
                run()

    def test_a_wrong_path_is_reported(self):
        with patch(TARGET) as http:
            http.get.return_value = response(404)
            http.post.return_value = response(404)
            with self.assertRaisesMessage(CommandError, "HTTP 404"):
                run()

    def test_an_incompatible_contract_fails(self):
        with patch(TARGET) as http:
            http.get.return_value = response(200, HEALTHY)
            http.post.return_value = response(200, {**PREDICTION, "contract_version": "2.0"})
            with self.assertRaisesMessage(CommandError, "incompatible"):
                run()

    @override_settings(AI_SERVICE_URL="")
    def test_a_disabled_ai_fails_without_calling_it(self):
        with patch(TARGET) as http, self.assertRaisesMessage(CommandError, "deshabilitada"):
            run()

        http.get.assert_not_called()
        http.post.assert_not_called()
