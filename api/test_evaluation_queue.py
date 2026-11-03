"""Pruebas de la evaluación diferida de la IA y de drain_ai_queue."""
import json
from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Alert, Node, RiskAssessment, SensorReading
from .services.evaluation_queue import drain, evaluate_pending, load_batch, pending_count

_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "login": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


INGEST_KEY = "test-ingest-key"
AI_URL = "http://ia.test"


def ai_reply(risk="FIRE", probability=0.95):
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(
        {
            "status": "ok",
            "contract_version": "1.0",
            "node_id": "NODE-001",
            "model_version": "test-1.0",
            "model_prediction": risk,
            "risk_level": risk,
            "risk_probability": probability,
            "probabilities": {"NORMAL": 0.02, "WARNING": 0.03, "FIRE": 0.95},
            "safety_rules": {"rule": "NONE", "explanation": "Señales concordantes."},
        }
    ).encode("utf-8")
    return response


@override_settings(INGEST_API_KEY=INGEST_KEY, AI_SERVICE_URL=AI_URL, AI_ASYNC_EVALUATION=True)
class DeferredIngestionTests(APITestCase):
    def setUp(self):
        Node.objects.create(node_id="NODE-001")
        self.counter = 0

    def ingest(self, temperature=25.0, smoke=10, flame=False):
        self.counter += 1
        return self.client.post(
            reverse("receive_reading"),
            {
                "node_id": "NODE-001",
                "temperature": temperature,
                "humidity": 40.0,
                "smoke": smoke,
                "flame": flame,
                "timestamp": f"2026-10-30T12:{self.counter:02d}:00Z",
            },
            format="json",
            HTTP_X_API_KEY=INGEST_KEY,
        )

    def test_the_ai_is_not_called_during_ingestion(self):
        with patch("api.services.ai_client.requests.post") as post:
            response = self.ingest()

        post.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["reading"]["ai"]["status"], "PENDING")

    def test_the_rules_still_decide_the_risk_right_away(self):
        with patch("api.services.ai_client.requests.post"):
            response = self.ingest(temperature=90, smoke=900, flame=True)

        self.assertEqual(response.data["risk_level"], "FIRE")
        self.assertIsNotNone(response.data["alert_id"])

    def test_the_assessment_waits_in_the_queue(self):
        with patch("api.services.ai_client.requests.post"):
            self.ingest()
            self.ingest()

        self.assertEqual(pending_count(), 2)

    @override_settings(AI_ASYNC_EVALUATION=False)
    def test_it_is_off_by_default_and_the_ai_is_called_inline(self):
        with patch("api.services.ai_client.requests.post", return_value=ai_reply("NORMAL", 0.1)) as post:
            response = self.ingest()

        post.assert_called_once()
        self.assertEqual(response.data["reading"]["ai"]["status"], "OK")
        self.assertEqual(pending_count(), 0)

    @override_settings(AI_SERVICE_URL="")
    def test_without_an_ai_service_nothing_is_deferred(self):
        response = self.ingest()

        self.assertEqual(response.data["reading"]["ai"]["status"], "DISABLED")
        self.assertEqual(pending_count(), 0)


@override_settings(AI_SERVICE_URL=AI_URL, AI_API_KEY="")
class DrainTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-001")
        self.counter = 0

    def pending(self, temperature=25.0, smoke=10, flame=False):
        self.counter += 1
        reading = SensorReading.objects.create(
            node=self.node, temperature=temperature, humidity=40, smoke=smoke, flame=flame,
        )
        return RiskAssessment.objects.create(
            reading=reading, risk_level="NORMAL", rule_reasons=[],
            ai_status=RiskAssessment.AIStatus.PENDING,
        )

    def test_the_batch_is_ordered_oldest_first(self):
        first, second, third = self.pending(), self.pending(), self.pending()

        queue = load_batch(10)

        self.assertEqual(list(queue), [first.pk, second.pk, third.pk])

    def test_the_batch_respects_the_limit_and_skips_resolved_ones(self):
        resolved = self.pending()
        RiskAssessment.objects.filter(pk=resolved.pk).update(ai_status="OK")
        pending = [self.pending() for _ in range(3)]

        self.assertEqual(list(load_batch(2)), [pending[0].pk, pending[1].pk])

    def test_draining_completes_the_assessments_in_order(self):
        calls = []

        def reply(*args, **kwargs):
            calls.append(kwargs["json"]["temperature"])
            return ai_reply("NORMAL", 0.1)

        for temperature in (21, 22, 23):
            self.pending(temperature=temperature)

        with patch("api.services.ai_client.requests.post", side_effect=reply):
            result = drain()

        self.assertEqual(result.evaluated, 3)
        self.assertFalse(result.stopped_early)
        self.assertEqual(calls, [21, 22, 23])
        self.assertEqual(pending_count(), 0)
        assessment = RiskAssessment.objects.first()
        self.assertEqual(assessment.ai_status, "OK")
        self.assertEqual(assessment.ai_model_version, "test-1.0")
        self.assertEqual(assessment.ai_probability, 0.1)

    def test_the_ai_can_raise_the_risk_and_create_the_alert(self):
        assessment = self.pending(temperature=55, smoke=400)  # solo las reglas: WARNING a lo sumo

        with patch("api.services.ai_client.requests.post", return_value=ai_reply("FIRE", 0.95)):
            drain()

        assessment.refresh_from_db()
        self.assertEqual(assessment.risk_level, "FIRE")
        self.assertEqual(Alert.objects.filter(level="FIRE").count(), 1)
        self.assertTrue(any("IA" in reason for reason in assessment.rule_reasons))

    def test_a_fire_after_the_ai_warns_the_neighbors(self):
        self.pending(temperature=55, smoke=400)

        with patch("api.services.ai_client.requests.post", return_value=ai_reply("FIRE", 0.95)):
            with patch("api.services.evaluation_queue.warn_neighbors_of_fire") as warn:
                drain()

        warn.assert_called_once_with("NODE-001")

    def test_a_down_ai_stops_the_drain_and_leaves_the_rest_pending(self):
        for _ in range(3):
            self.pending()

        with patch("api.services.ai_client.requests.post", side_effect=requests.ConnectTimeout("caída")) as post:
            with self.assertLogs("api.ai", level="WARNING"):
                result = drain()

        self.assertEqual(post.call_count, 1)  # no espera un timeout por cada pendiente
        self.assertTrue(result.stopped_early)
        self.assertEqual(result.deferred, 1)
        self.assertEqual(result.evaluated, 0)
        self.assertEqual(pending_count(), 3)

    def test_they_are_retried_on_the_next_run(self):
        self.pending()
        with patch("api.services.ai_client.requests.post", side_effect=requests.ConnectTimeout("caída")):
            with self.assertLogs("api.ai", level="WARNING"):
                drain()

        with patch("api.services.ai_client.requests.post", return_value=ai_reply("NORMAL", 0.1)):
            result = drain()

        self.assertEqual(result.evaluated, 1)
        self.assertEqual(pending_count(), 0)

    def test_a_rejected_reading_is_resolved_and_not_retried_forever(self):
        self.pending()
        rejected = requests.Response()
        rejected.status_code = 403
        rejected._content = b"{}"

        with patch("api.services.ai_client.requests.post", return_value=rejected):
            with self.assertLogs("api.ai", level="ERROR"):
                result = drain()

        self.assertEqual(result.evaluated, 1)
        self.assertEqual(RiskAssessment.objects.get().ai_status, "REJECTED")
        self.assertEqual(pending_count(), 0)

    def test_the_limit_caps_the_work_of_one_run(self):
        for _ in range(5):
            self.pending()

        with patch("api.services.ai_client.requests.post", return_value=ai_reply("NORMAL", 0.1)):
            result = drain(limit=2)

        self.assertEqual(result.evaluated, 2)
        self.assertEqual(pending_count(), 3)

    def test_an_assessment_already_handled_is_skipped(self):
        assessment = self.pending()
        RiskAssessment.objects.filter(pk=assessment.pk).update(ai_status="OK")

        with patch("api.services.ai_client.requests.post") as post:
            self.assertEqual(evaluate_pending(assessment.pk), "skipped")

        post.assert_not_called()

    def test_an_empty_queue_does_nothing(self):
        with patch("api.services.ai_client.requests.post") as post:
            result = drain()

        post.assert_not_called()
        self.assertEqual((result.evaluated, result.skipped, result.deferred), (0, 0, 0))


@override_settings(AI_SERVICE_URL=AI_URL, AI_API_KEY="")
class DrainCommandTests(TestCase):
    def run_command(self, **options):
        out = StringIO()
        call_command("drain_ai_queue", stdout=out, **options)
        return out.getvalue()

    def test_reports_what_it_did(self):
        node = Node.objects.create(node_id="NODE-001")
        reading = SensorReading.objects.create(node=node, temperature=20, humidity=40, smoke=1, flame=False)
        RiskAssessment.objects.create(
            reading=reading, risk_level="NORMAL", rule_reasons=[],
            ai_status=RiskAssessment.AIStatus.PENDING,
        )

        with patch("api.services.ai_client.requests.post", return_value=ai_reply("NORMAL", 0.1)):
            output = self.run_command()

        self.assertIn("Evaluadas: 1", output)
        self.assertIn("Pendientes: 0", output)

    def test_warns_when_the_ai_does_not_answer(self):
        node = Node.objects.create(node_id="NODE-001")
        reading = SensorReading.objects.create(node=node, temperature=20, humidity=40, smoke=1, flame=False)
        RiskAssessment.objects.create(
            reading=reading, risk_level="NORMAL", rule_reasons=[],
            ai_status=RiskAssessment.AIStatus.PENDING,
        )

        with patch("api.services.ai_client.requests.post", side_effect=requests.ConnectTimeout("caída")):
            with self.assertLogs("api.ai", level="WARNING"):
                output = self.run_command()

        self.assertIn("Pendientes: 1", output)
        self.assertIn("La IA no respondió", output)

    def test_an_invalid_limit_is_rejected(self):
        with self.assertRaises(CommandError):
            self.run_command(limit=0)

    def test_an_empty_queue(self):
        output = self.run_command()

        self.assertIn("Evaluadas: 0", output)
        self.assertIn("Pendientes: 0", output)
