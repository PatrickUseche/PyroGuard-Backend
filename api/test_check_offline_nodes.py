"""Pruebas del comando check_offline_nodes y de su aviso de nodos desconectados."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Alert, Node, NotificationOutbox, SensorReading


@override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=300, NOTIFICATION_COOLDOWN_SECONDS=300)
class CheckOfflineNodesTests(TestCase):
    def node(self, node_id, seconds_ago=None):
        last = None if seconds_ago is None else timezone.now() - timedelta(seconds=seconds_ago)
        return Node.objects.create(node_id=node_id, last_communication=last)

    def alert(self, node, level="FIRE", status=Alert.Status.ACTIVE):
        reading = SensorReading.objects.create(node=node, temperature=20, humidity=40, smoke=1, flame=False)
        return Alert.objects.create(node=node, reading=reading, level=level, message="m", status=status)

    def run_command(self, **options):
        out = StringIO()
        call_command("check_offline_nodes", stdout=out, **options)
        return out.getvalue()

    def test_when_everything_is_online(self):
        self.node("A", seconds_ago=10)

        output = self.run_command()

        self.assertIn("están conectados", output)
        self.assertEqual(NotificationOutbox.objects.count(), 0)

    def test_lists_only_the_offline_nodes(self):
        self.node("ONLINE", seconds_ago=10)
        self.node("OFFLINE-1", seconds_ago=3600)
        self.node("OFFLINE-2", seconds_ago=900)

        output = self.run_command(no_notify=True)

        self.assertIn("Nodos desconectados: 2", output)
        self.assertIn("OFFLINE-1: sin comunicación desde hace 60 min", output)
        self.assertIn("OFFLINE-2: sin comunicación desde hace 15 min", output)
        self.assertNotIn("ONLINE:", output)

    def test_the_most_silent_node_is_listed_first(self):
        self.node("RECENT", seconds_ago=600)
        self.node("OLD", seconds_ago=7200)

        output = self.run_command(no_notify=True)

        self.assertLess(output.index("OLD"), output.index("RECENT"))

    def test_nodes_that_never_communicated_are_not_offline(self):
        self.node("NEVER")

        self.assertIn("están conectados", self.run_command())

    def test_the_threshold_comes_from_the_settings(self):
        self.node("A", seconds_ago=120)

        with override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=60):
            self.assertIn("Nodos desconectados: 1", self.run_command(no_notify=True))
        with override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=600):
            self.assertIn("están conectados", self.run_command(no_notify=True))

    def test_an_offline_node_with_an_active_alert_is_notified(self):
        node = self.node("A", seconds_ago=3600)
        self.alert(node, "FIRE")

        output = self.run_command()

        notice = NotificationOutbox.objects.get()
        self.assertEqual((notice.kind, notice.priority, notice.node), ("OFFLINE_ALERT", 2, node))
        self.assertIn("desconectado con una alerta FIRE activa", notice.subject)
        self.assertIn("riesgo actual es desconocido", notice.message)
        self.assertIn("Avisos encolados: 1", output)

    def test_an_acknowledged_alert_also_counts(self):
        self.alert(self.node("A", seconds_ago=3600), "WARNING", Alert.Status.ACKNOWLEDGED)

        self.run_command()

        self.assertEqual(NotificationOutbox.objects.count(), 1)

    def test_a_closed_alert_does_not_notify(self):
        self.alert(self.node("A", seconds_ago=3600), "FIRE", Alert.Status.CLOSED)

        output = self.run_command()

        self.assertEqual(NotificationOutbox.objects.count(), 0)
        self.assertIn("Avisos encolados: 0", output)

    def test_an_offline_node_without_alerts_does_not_notify(self):
        self.node("A", seconds_ago=3600)

        output = self.run_command()

        self.assertEqual(NotificationOutbox.objects.count(), 0)
        self.assertIn("Avisos encolados: 0", output)

    def test_the_most_serious_active_alert_is_the_one_reported(self):
        node = self.node("A", seconds_ago=3600)
        self.alert(node, "WARNING")
        self.alert(node, "FIRE")

        self.run_command()

        self.assertIn("alerta FIRE", NotificationOutbox.objects.get().subject)

    def test_an_online_node_with_an_alert_does_not_notify(self):
        self.alert(self.node("A", seconds_ago=10), "FIRE")

        self.run_command()

        self.assertEqual(NotificationOutbox.objects.count(), 0)

    def test_no_notify_only_lists(self):
        self.alert(self.node("A", seconds_ago=3600), "FIRE")

        output = self.run_command(no_notify=True)

        self.assertEqual(NotificationOutbox.objects.count(), 0)
        self.assertNotIn("Avisos encolados", output)

    def test_running_it_again_inside_the_window_does_not_repeat_the_notice(self):
        self.alert(self.node("A", seconds_ago=3600), "FIRE")

        self.run_command()
        output = self.run_command()

        self.assertEqual(NotificationOutbox.objects.count(), 1)
        self.assertIn("Avisos encolados: 0", output)

    def test_each_offline_node_with_an_alert_gets_its_own_notice(self):
        for node_id in ("A", "B"):
            self.alert(self.node(node_id, seconds_ago=3600), "FIRE")

        self.run_command()

        self.assertEqual(NotificationOutbox.objects.count(), 2)
