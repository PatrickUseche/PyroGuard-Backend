"""Pruebas del comando seed_demo."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Alert, Node, NodeLink, RiskAssessment, SensorReading
from .services.node_graph import node_graph
from .services.risk_zones import get_risk_zones


def seed(**options):
    out = StringIO()
    call_command("seed_demo", stdout=out, **options)
    return out.getvalue()


@override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=300, NOTIFICATION_COOLDOWN_SECONDS=0)
class SeedDemoTests(TestCase):
    def setUp(self):
        node_graph.clear()
        self.addCleanup(node_graph.clear)

    def test_creates_the_requested_nodes_with_their_data(self):
        output = seed(nodes=5, hours=4, seed=1)

        self.assertEqual(Node.objects.count(), 5)
        self.assertEqual(
            list(Node.objects.values_list("node_id", flat=True)),
            ["SIM-001", "SIM-002", "SIM-003", "SIM-004", "SIM-005"],
        )
        self.assertIn("Se crearon 5 nodos", output)
        self.assertTrue(all(node.latitude and node.longitude for node in Node.objects.all()))

    def test_nodes_are_linked_in_a_ring(self):
        seed(nodes=5, hours=3, seed=1)
        node_graph.clear()

        self.assertEqual(NodeLink.objects.count(), 5)
        self.assertEqual(node_graph.direct_neighbors("SIM-001"), ["SIM-002", "SIM-005"])
        self.assertEqual(node_graph.direct_neighbors("SIM-003"), ["SIM-002", "SIM-004"])

    def test_three_nodes_form_a_triangle(self):
        seed(nodes=3, hours=3, seed=1)

        self.assertEqual(NodeLink.objects.count(), 3)

    def test_every_reading_has_a_risk_assessment(self):
        seed(nodes=4, hours=3, seed=1)

        self.assertEqual(SensorReading.objects.count(), RiskAssessment.objects.count())
        self.assertGreater(SensorReading.objects.count(), 0)

    def test_readings_are_spaced_ten_minutes_apart(self):
        seed(nodes=3, hours=3, seed=1)

        readings = SensorReading.objects.filter(node__node_id="SIM-003").order_by("timestamp")
        stamps = list(readings.values_list("timestamp", flat=True))
        gaps = {(later - earlier) for earlier, later in zip(stamps, stamps[1:], strict=False)}
        self.assertEqual(gaps, {timedelta(minutes=10)})

    def test_the_first_node_ends_in_fire_and_the_second_in_warning(self):
        seed(nodes=5, hours=4, seed=1)

        def current(node_id):
            return RiskAssessment.objects.filter(reading__node__node_id=node_id).order_by("-reading__timestamp").first()

        self.assertEqual(current("SIM-001").risk_level, "FIRE")
        self.assertEqual(current("SIM-002").risk_level, "WARNING")
        self.assertEqual(current("SIM-003").risk_level, "NORMAL")

    def test_the_fire_creates_an_alert(self):
        seed(nodes=5, hours=4, seed=1)

        alert = Alert.objects.get()
        self.assertEqual((alert.node.node_id, alert.level), ("SIM-001", "FIRE"))

    def test_the_last_node_is_offline_and_the_rest_online(self):
        seed(nodes=5, hours=4, seed=1)

        statuses = {node.node_id: node.connection_status for node in Node.objects.all()}

        self.assertEqual(statuses["SIM-005"], "OFFLINE")
        self.assertEqual({statuses[f"SIM-00{n}"] for n in range(1, 5)}, {"ONLINE"})

    def test_the_offline_node_stopped_two_hours_ago(self):
        seed(nodes=4, hours=5, seed=1)

        last = SensorReading.objects.filter(node__node_id="SIM-004").latest("timestamp").timestamp

        self.assertGreaterEqual(timezone.now() - last, timedelta(hours=2))
        self.assertLess(timezone.now() - last, timedelta(hours=2, minutes=11))

    def test_the_risky_neighbors_form_a_zone(self):
        seed(nodes=5, hours=4, seed=1)
        node_graph.clear()

        (zone,) = get_risk_zones()

        self.assertEqual((zone["zone_id"], zone["risk_level"], zone["size"]), ("SIM-001", "FIRE", 2))

    def test_the_same_seed_gives_the_same_values(self):
        seed(nodes=4, hours=3, seed=42)
        first = list(SensorReading.objects.order_by("node__node_id", "timestamp").values_list("temperature", "smoke"))
        Node.objects.all().delete()

        seed(nodes=4, hours=3, seed=42)
        second = list(SensorReading.objects.order_by("node__node_id", "timestamp").values_list("temperature", "smoke"))

        self.assertEqual(first, second)

    def test_different_seeds_give_different_values(self):
        seed(nodes=4, hours=3, seed=1)
        first = list(SensorReading.objects.order_by("node__node_id", "timestamp").values_list("temperature", flat=True))
        Node.objects.all().delete()

        seed(nodes=4, hours=3, seed=2)
        second = list(
            SensorReading.objects.order_by("node__node_id", "timestamp").values_list("temperature", flat=True)
        )

        self.assertNotEqual(first, second)

    def test_running_it_twice_without_reset_is_refused(self):
        seed(nodes=3, hours=3, seed=1)

        with self.assertRaises(CommandError):
            seed(nodes=3, hours=3, seed=1)

        self.assertEqual(Node.objects.count(), 3)

    def test_reset_replaces_the_demo_nodes_only(self):
        other = Node.objects.create(node_id="PROD-001")
        seed(nodes=3, hours=3, seed=1)

        seed(nodes=4, hours=3, seed=1, reset=True)

        self.assertEqual(Node.objects.filter(node_id__startswith="SIM-").count(), 4)
        self.assertTrue(Node.objects.filter(pk=other.pk).exists())
        self.assertEqual(Alert.objects.count(), 1)

    def test_invalid_options_are_rejected(self):
        for options in ({"nodes": 2}, {"nodes": 51}, {"hours": 2}, {"hours": 73}):
            with self.subTest(options=options):
                with self.assertRaises(CommandError):
                    seed(**options)
        self.assertEqual(Node.objects.count(), 0)

    def test_the_data_is_visible_through_the_api(self):
        seed(nodes=5, hours=4, seed=1)

        summary = self.client.get(reverse("dashboard_summary")).json()

        self.assertEqual(summary["total_nodes"], 5)
        self.assertEqual(summary["nodes_offline"], 1)
        self.assertEqual(summary["overall_risk"], "FIRE")
        self.assertEqual(summary["active_alerts"], 1)
