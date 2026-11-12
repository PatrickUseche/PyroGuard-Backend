"""Prueba de la migración 0011: limpia duplicados antes de crear la restricción única."""
from datetime import datetime
from datetime import timezone as dt_timezone

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

MOMENT = datetime(2026, 10, 30, 12, 0, tzinfo=dt_timezone.utc)


class RemoveDuplicateReadingsMigrationTests(TransactionTestCase):
    before = [("api", "0010_operators_group")]
    after = [("api", "0011_reading_unique_node_timestamp")]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_keeps_the_reading_with_an_alert_and_otherwise_the_oldest(self):
        apps = self.migrate(self.before)
        node_model = apps.get_model("api", "Node")
        reading_model = apps.get_model("api", "SensorReading")
        alert_model = apps.get_model("api", "Alert")
        node = node_model.objects.create(node_id="NODE-001")
        values = {"node": node, "temperature": 25, "humidity": 40, "smoke": 1}
        plain_first = reading_model.objects.create(timestamp=MOMENT, **values)
        with_alert = reading_model.objects.create(timestamp=MOMENT, **values)
        alert_model.objects.create(node=node, reading=with_alert, level="FIRE", message="x")
        other_a = reading_model.objects.create(timestamp=MOMENT.replace(minute=1), **values)
        reading_model.objects.create(timestamp=MOMENT.replace(minute=1), **values)

        apps = self.migrate(self.after)
        reading_model = apps.get_model("api", "SensorReading")

        remaining = set(reading_model.objects.values_list("pk", flat=True))
        self.assertEqual(len(remaining), 2)
        self.assertIn(with_alert.pk, remaining)
        self.assertNotIn(plain_first.pk, remaining)
        self.assertIn(other_a.pk, remaining)
