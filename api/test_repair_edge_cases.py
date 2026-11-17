"""Ramas de `repair_unassessed` y de la cola de evaluación que la cobertura marcaba sin probar."""
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Node, RiskAssessment, SensorReading
from .services import evaluation_queue
from .services.ai_client import AIPrediction

FIRE = {"temperature": 75, "humidity": 8, "smoke": 900, "gas": 0, "flame": True}
CALM = {"temperature": 22, "humidity": 60, "smoke": 5, "gas": 0, "flame": False}


@override_settings(AI_SERVICE_URL="", AI_ASYNC_EVALUATION=False)
class RepairEdgeCaseTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="REP-1")

    def unassessed(self, minutes_ago=5, **values):
        return SensorReading.objects.create(
            node=self.node, timestamp=timezone.now() - timedelta(minutes=minutes_ago), **{**CALM, **values}
        )

    def test_a_reading_assessed_by_another_process_is_skipped(self):
        self.unassessed()
        with patch.object(evaluation_queue, "_assess_unassessed", side_effect=IntegrityError("ya evaluada")):
            self.assertEqual(evaluation_queue.repair_unassessed(), 0)

    def test_an_unexpected_failure_is_logged_and_the_next_reading_is_repaired(self):
        first, second = self.unassessed(minutes_ago=10), self.unassessed(minutes_ago=5)
        real = evaluation_queue._assess_unassessed

        def fail_first(reading_id):
            if reading_id == first.pk:
                raise RuntimeError("fallo puntual")
            return real(reading_id)

        with (
            patch.object(evaluation_queue, "_assess_unassessed", side_effect=fail_first),
            self.assertLogs("api.readings", level="ERROR") as logs,
        ):
            self.assertEqual(evaluation_queue.repair_unassessed(), 1)

        self.assertIn(f"id={first.pk}", " ".join(logs.output))
        self.assertTrue(RiskAssessment.objects.filter(reading=second).exists())

    def test_a_reading_that_is_already_assessed_is_not_repaired_twice(self):
        self.assertFalse(evaluation_queue._assess_unassessed(999_999))

    @override_settings(AI_SERVICE_URL="http://ia.test", AI_ASYNC_EVALUATION=True)
    def test_with_deferred_ai_the_repaired_reading_stays_pending_for_the_ai(self):
        reading = self.unassessed()
        with patch.object(evaluation_queue, "_predict") as predict:
            self.assertEqual(evaluation_queue.repair_unassessed(), 1)

        predict.assert_not_called()
        self.assertEqual(SensorReading.objects.get(pk=reading.pk).assessment.ai_status, evaluation_queue.PENDING)

    def test_the_ai_explanation_is_kept_in_the_reasons(self):
        reading = self.unassessed()
        prediction = AIPrediction(
            status=RiskAssessment.AIStatus.OK, risk_level="NORMAL", probability=0.05, explanation="sin señales de humo"
        )
        with patch.object(evaluation_queue, "_predict", return_value=prediction):
            evaluation_queue.repair_unassessed()

        reasons = RiskAssessment.objects.get(reading=reading).rule_reasons
        self.assertIn("IA: sin señales de humo", reasons)

    def test_a_failure_warning_the_neighbours_does_not_undo_the_repair(self):
        reading = self.unassessed(**FIRE)
        with (
            patch.object(evaluation_queue, "warn_neighbors_of_fire", side_effect=RuntimeError("grafo")),
            self.assertLogs("api.readings", level="ERROR") as logs,
        ):
            self.assertEqual(evaluation_queue.repair_unassessed(), 1)

        self.assertEqual(RiskAssessment.objects.get(reading=reading).risk_level, RiskAssessment.RiskLevel.FIRE)
        self.assertIn("vecinos", " ".join(logs.output))
