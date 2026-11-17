"""Respuestas de la IA que el contrato no contempla."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from .models import Node, RiskAssessment, SensorReading
from .services.ai_client import request_prediction


@override_settings(AI_SERVICE_URL="http://ia.test", AI_API_KEY="")
class UnexpectedAIStatusTests(SimpleTestCase):
    def setUp(self):
        self.reading = SensorReading(
            node=Node(node_id="AI-EDGE"), temperature=22, humidity=60, smoke=5, gas=0, flame=False,
            timestamp=timezone.now(),
        )

    def test_an_unexpected_status_code_is_an_invalid_response(self):
        # Ni 200, ni 4xx, ni 5xx: p. ej. un 204 sin cuerpo o una redirección que requests no siguió.
        for code in (201, 204, 302, 304):
            response = MagicMock(status_code=code)
            response.json.return_value = {}
            with (
                self.subTest(code=code),
                patch("api.services.ai_client.requests.post", return_value=response),
                self.assertLogs("api.ai", level="WARNING"),
            ):
                prediction = request_prediction(self.reading)
                self.assertEqual(prediction.status, RiskAssessment.AIStatus.INVALID_RESPONSE)
