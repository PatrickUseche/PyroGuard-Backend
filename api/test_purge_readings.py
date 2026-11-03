"""Pruebas del comando purge_readings."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Alert, Node, RiskAssessment, SensorReading


class PurgeReadingsTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-001")

    def reading(self, days_ago):
        return SensorReading.objects.create(
            node=self.node,
            temperature=20,
            humidity=40,
            smoke=1,
            flame=False,
            timestamp=timezone.now() - timedelta(days=days_ago),
        )

    def purge(self, *args, **options):
        out = StringIO()
        call_command("purge_readings", *args, stdout=out, **options)
        return out.getvalue()

    @override_settings(READINGS_RETENTION_DAYS=30)
    def test_deletes_only_readings_older_than_the_retention(self):
        old = self.reading(31)
        recent = self.reading(29)

        output = self.purge()

        self.assertFalse(SensorReading.objects.filter(pk=old.pk).exists())
        self.assertTrue(SensorReading.objects.filter(pk=recent.pk).exists())
        self.assertIn("Se borraron 1 lectura(s)", output)

    @override_settings(READINGS_RETENTION_DAYS=30)
    def test_the_days_option_overrides_the_setting(self):
        self.reading(10)

        self.purge(days=5)

        self.assertEqual(SensorReading.objects.count(), 0)

    def test_the_default_retention_is_ninety_days(self):
        self.reading(89)
        self.reading(91)

        self.purge()

        self.assertEqual(SensorReading.objects.count(), 1)

    def test_deletes_the_assessments_of_the_purged_readings(self):
        old = self.reading(100)
        RiskAssessment.objects.create(reading=old, risk_level="NORMAL", rule_reasons=[])

        self.purge()

        self.assertEqual(RiskAssessment.objects.count(), 0)

    def test_keeps_readings_that_caused_an_alert(self):
        with_alert = self.reading(200)
        Alert.objects.create(
            node=self.node, reading=with_alert, level=Alert.Level.FIRE, message="Incendio"
        )
        without_alert = self.reading(200)

        self.purge()

        self.assertTrue(SensorReading.objects.filter(pk=with_alert.pk).exists())
        self.assertFalse(SensorReading.objects.filter(pk=without_alert.pk).exists())
        self.assertEqual(Alert.objects.count(), 1)

    def test_deletes_in_batches_until_nothing_is_left(self):
        for _ in range(7):
            self.reading(120)
        keep = self.reading(1)

        output = self.purge(batch_size=3)

        self.assertEqual(list(SensorReading.objects.values_list("pk", flat=True)), [keep.pk])
        self.assertIn("Se borraron 7 lectura(s)", output)

    def test_dry_run_only_counts(self):
        self.reading(120)
        self.reading(130)

        output = self.purge(dry_run=True)

        self.assertEqual(SensorReading.objects.count(), 2)
        self.assertIn("Se borrarían 2 lectura(s)", output)

    def test_nothing_to_delete(self):
        self.reading(1)

        output = self.purge()

        self.assertIn("Se borraron 0 lectura(s)", output)
        self.assertEqual(SensorReading.objects.count(), 1)

    def test_other_nodes_are_purged_too(self):
        other = Node.objects.create(node_id="NODE-002")
        SensorReading.objects.create(
            node=other, temperature=20, humidity=40, smoke=1, flame=False,
            timestamp=timezone.now() - timedelta(days=500),
        )

        self.purge()

        self.assertEqual(SensorReading.objects.count(), 0)
        self.assertEqual(Node.objects.count(), 2)

    def test_invalid_options_are_rejected(self):
        for options in ({"days": 0}, {"days": -3}, {"batch_size": 0}):
            with self.subTest(options=options):
                with self.assertRaises(CommandError):
                    self.purge(**options)
