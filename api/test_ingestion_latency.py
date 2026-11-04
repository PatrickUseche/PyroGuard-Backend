"""Medición de la latencia de la ingesta con la IA lenta o caída.

Estas pruebas documentan el problema que justifica la cola de evaluación (4.13):
mientras la ingesta pide la predicción de forma síncrona, la respuesta al sensor
tarda lo que tarde la IA, hasta ``AI_CONNECT_TIMEOUT + AI_READ_TIMEOUT`` en el peor
caso. Se usa un retardo pequeño y simulado para que la prueba sea rápida, pero la
conclusión es proporcional: con los 3 s + 10 s por defecto, un sensor esperaría hasta
13 s por lectura.
"""
import json
import time
from unittest.mock import patch

import requests
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Node, RiskAssessment, SensorReading

_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "google_login": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


AI_DELAY = 0.4
INGEST_KEY = "test-ingest-key"


def ok_response():
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(
        {
            "status": "ok",
            "contract_version": "1.0",
            "node_id": "NODE-001",
            "model_version": "test-1.0",
            "model_prediction": "NORMAL",
            "risk_level": "NORMAL",
            "risk_probability": 0.1,
            "probabilities": {"NORMAL": 0.9, "WARNING": 0.08, "FIRE": 0.02},
            "safety_rules": {"rule": "NONE", "explanation": ""},
        }
    ).encode("utf-8")
    return response


@override_settings(INGEST_API_KEY=INGEST_KEY, AI_SERVICE_URL="http://ia.test")
class IngestionLatencyTests(APITestCase):
    def setUp(self):
        Node.objects.create(node_id="NODE-001")
        self.counter = 0

    def ingest(self):
        self.counter += 1
        started = time.perf_counter()
        response = self.client.post(
            reverse("receive_reading"),
            {
                "node_id": "NODE-001",
                "temperature": 25.0,
                "humidity": 40.0,
                "smoke": 10,
                "flame": False,
                "timestamp": f"2026-10-30T12:{self.counter:02d}:00Z",
            },
            format="json",
            HTTP_X_API_KEY=INGEST_KEY,
        )
        return response, time.perf_counter() - started

    def slow_ai(self, *args, **kwargs):
        time.sleep(AI_DELAY)
        return ok_response()

    def failing_ai(self, *args, **kwargs):
        time.sleep(AI_DELAY)  # lo que tarda en vencer el timeout
        raise requests.ConnectTimeout("sin respuesta")

    def test_a_fast_ai_adds_almost_nothing(self):
        with patch("api.services.ai_client.requests.post", return_value=ok_response()):
            response, latency = self.ingest()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertLess(latency, AI_DELAY)

    def test_a_slow_ai_delays_the_response_to_the_sensor(self):
        with patch("api.services.ai_client.requests.post", side_effect=self.slow_ai):
            response, latency = self.ingest()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertGreaterEqual(latency, AI_DELAY)
        self.assertEqual(response.data["reading"]["ai"]["status"], "OK")

    def test_a_down_ai_delays_the_response_until_the_timeout(self):
        with patch("api.services.ai_client.requests.post", side_effect=self.failing_ai):
            with self.assertLogs("api.ai", level="WARNING"):
                response, latency = self.ingest()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertGreaterEqual(latency, AI_DELAY)
        self.assertEqual(response.data["reading"]["ai"]["status"], "UNAVAILABLE")

    def test_the_reading_is_safe_even_if_the_ai_is_down(self):
        with patch("api.services.ai_client.requests.post", side_effect=self.failing_ai):
            with self.assertLogs("api.ai", level="WARNING"):
                self.ingest()

        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertEqual(RiskAssessment.objects.get().ai_status, "UNAVAILABLE")

    def test_latency_grows_with_every_reading_while_the_ai_is_down(self):
        with patch("api.services.ai_client.requests.post", side_effect=self.failing_ai):
            with self.assertLogs("api.ai", level="WARNING"):
                latencies = [self.ingest()[1] for _ in range(3)]

        self.assertTrue(all(latency >= AI_DELAY for latency in latencies))

    def test_worst_case_with_the_default_timeouts(self):
        from django.conf import settings

        worst_case = settings.AI_CONNECT_TIMEOUT + settings.AI_READ_TIMEOUT

        self.assertEqual(worst_case, 13.0)
