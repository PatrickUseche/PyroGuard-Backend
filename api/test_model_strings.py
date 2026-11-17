"""Representación en texto de los modelos (la usan el admin y los logs)."""
from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from .models import GoogleAccount, Node, NotificationOutbox, RiskAssessment, SensorReading

MOMENT = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


class ModelStringTests(SimpleTestCase):
    def test_notification_outbox_shows_kind_subject_and_status(self):
        notification = NotificationOutbox(
            kind=NotificationOutbox.Kind.FIRE_ALERT, subject="Incendio en NODE-001", priority=1, message="..."
        )
        self.assertEqual(str(notification), "FIRE_ALERT - Incendio en NODE-001 - PENDING")

    def test_risk_assessment_shows_its_reading_and_level(self):
        reading = SensorReading(node=Node(node_id="NODE-001"), timestamp=MOMENT)
        assessment = RiskAssessment(reading=reading, risk_level=RiskAssessment.RiskLevel.FIRE)
        self.assertEqual(str(assessment), f"NODE-001 - {MOMENT} - FIRE")

    def test_google_account_shows_the_user_and_the_google_id(self):
        account = GoogleAccount(user=get_user_model()(username="ada"), google_sub="1234567890")
        self.assertEqual(str(account), "ada (1234567890)")
