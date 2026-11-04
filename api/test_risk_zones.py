"""Pruebas de las zonas de riesgo (nodos vecinos en riesgo a la vez)."""
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Node, NodeLink, RiskAssessment, SensorReading
from .services.node_graph import node_graph
from .services.risk_zones import get_risk_zones

_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "google_login": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


class RiskZonesTests(APITestCase):
    def setUp(self):
        node_graph.clear()
        self.addCleanup(node_graph.clear)
        self.nodes = {}

    def node(self, node_id, risk=None, offline=False):
        node = Node.objects.create(
            node_id=node_id,
            last_communication=timezone.now() - timedelta(hours=5 if offline else 0, seconds=1),
        )
        self.nodes[node_id] = node
        if risk:
            reading = SensorReading.objects.create(
                node=node, temperature=20, humidity=40, smoke=1, flame=False
            )
            RiskAssessment.objects.create(reading=reading, risk_level=risk, rule_reasons=[])
        return node

    def link(self, *pairs):
        for first, second in pairs:
            NodeLink.objects.create(node_a=self.nodes[first], node_b=self.nodes[second])

    def zones(self):
        return self.client.get(reverse("dashboard_zones"))

    def test_no_nodes_means_no_zones(self):
        response = self.zones()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_nodes_in_normal_state_form_no_zone(self):
        self.node("A", "NORMAL")
        self.node("B", "NORMAL")
        self.link(("A", "B"))

        self.assertEqual(self.zones().data, [])

    def test_connected_nodes_at_risk_form_one_zone(self):
        for node_id, risk in (("A", "WARNING"), ("B", "FIRE"), ("C", "WARNING")):
            self.node(node_id, risk)
        self.link(("A", "B"), ("B", "C"))

        zones = self.zones().data

        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["zone_id"], "A")
        self.assertEqual(zones[0]["risk_level"], "FIRE")
        self.assertEqual(zones[0]["size"], 3)
        self.assertEqual(
            zones[0]["nodes"],
            [
                {"node_id": "A", "current_risk": "WARNING"},
                {"node_id": "B", "current_risk": "FIRE"},
                {"node_id": "C", "current_risk": "WARNING"},
            ],
        )

    def test_nodes_at_risk_without_links_are_separate_zones(self):
        self.node("A", "WARNING")
        self.node("B", "WARNING")

        zones = self.zones().data

        self.assertEqual([zone["zone_id"] for zone in zones], ["A", "B"])
        self.assertEqual([zone["size"] for zone in zones], [1, 1])

    def test_a_node_in_normal_state_breaks_the_zone(self):
        self.node("A", "FIRE")
        self.node("B", "NORMAL")
        self.node("C", "FIRE")
        self.link(("A", "B"), ("B", "C"))

        zones = self.zones().data

        self.assertEqual([zone["zone_id"] for zone in zones], ["A", "C"])

    def test_a_node_without_assessment_is_not_part_of_a_zone(self):
        self.node("A", "FIRE")
        self.node("B")
        self.node("C", "FIRE")
        self.link(("A", "B"), ("B", "C"))

        self.assertEqual(len(self.zones().data), 2)

    def test_offline_nodes_are_left_out(self):
        self.node("A", "FIRE")
        self.node("B", "FIRE", offline=True)
        self.link(("A", "B"))

        zones = self.zones().data

        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["nodes"], [{"node_id": "A", "current_risk": "FIRE"}])

    def test_a_node_that_never_communicated_is_left_out(self):
        node = self.node("A", "FIRE")
        Node.objects.filter(pk=node.pk).update(last_communication=None)

        self.assertEqual(self.zones().data, [])

    def test_zones_are_ordered_by_risk_then_size_then_id(self):
        # A1-A3: tres nodos solo en WARNING; B1: un nodo en FIRE; C1-C2: FIRE y WARNING
        # enlazados; D1: un nodo en FIRE que empata en tamaño con B1.
        for node_id, risk in (
            ("A1", "WARNING"), ("A2", "WARNING"), ("A3", "WARNING"),
            ("B1", "FIRE"),
            ("C1", "FIRE"), ("C2", "WARNING"),
            ("D1", "FIRE"),
        ):
            self.node(node_id, risk)
        self.link(("A1", "A2"), ("A2", "A3"), ("C1", "C2"))

        zones = self.zones().data

        self.assertEqual([zone["zone_id"] for zone in zones], ["C1", "B1", "D1", "A1"])
        self.assertEqual([zone["risk_level"] for zone in zones], ["FIRE", "FIRE", "FIRE", "WARNING"])

    def test_two_separate_groups_stay_separate(self):
        for node_id in ("A", "B", "X", "Y"):
            self.node(node_id, "WARNING")
        self.link(("A", "B"), ("X", "Y"))

        zones = self.zones().data

        self.assertEqual({zone["zone_id"] for zone in zones}, {"A", "X"})
        self.assertTrue(all(zone["size"] == 2 for zone in zones))

    def test_a_cycle_is_a_single_zone(self):
        for node_id in ("A", "B", "C"):
            self.node(node_id, "FIRE")
        self.link(("A", "B"), ("B", "C"), ("A", "C"))

        self.assertEqual(len(self.zones().data), 1)

    def test_a_new_link_merges_two_zones(self):
        self.node("A", "FIRE")
        self.node("B", "FIRE")
        self.assertEqual(len(self.zones().data), 2)

        self.link(("A", "B"))

        self.assertEqual(len(self.zones().data), 1)

    def test_only_the_latest_assessment_counts(self):
        node = self.node("A", "FIRE")
        reading = SensorReading.objects.create(
            node=node, temperature=20, humidity=40, smoke=1, flame=False
        )
        RiskAssessment.objects.create(reading=reading, risk_level="NORMAL", rule_reasons=[])

        self.assertEqual(self.zones().data, [])

    def test_the_service_returns_the_same_data_as_the_endpoint(self):
        self.node("A", "FIRE")
        self.node("B", "WARNING")
        self.link(("A", "B"))

        self.assertEqual(get_risk_zones(), list(self.zones().data))

    def test_matches_a_brute_force_grouping_on_a_larger_graph(self):
        ids = [f"N{number:02d}" for number in range(20)]
        for number, node_id in enumerate(ids):
            self.node(node_id, "FIRE" if number % 3 else "NORMAL")
        pairs = set()
        for index in range(20):
            other = (index * 7 + 3) % 20
            if other != index:
                pairs.add(tuple(sorted((ids[index], ids[other]))))
        self.link(*sorted(pairs))
        risky = {node_id for number, node_id in enumerate(ids) if number % 3}

        adjacent = {node_id: set() for node_id in ids}
        for first, second in pairs:
            adjacent[first].add(second)
            adjacent[second].add(first)
        expected = []
        remaining = set(risky)
        while remaining:
            stack = [remaining.pop()]
            group = set(stack)
            while stack:
                for other in adjacent[stack.pop()] & risky:
                    if other not in group:
                        group.add(other)
                        stack.append(other)
            remaining -= group
            expected.append(sorted(group))

        found = [[item["node_id"] for item in zone["nodes"]] for zone in self.zones().data]

        self.assertEqual(sorted(found), sorted(expected))

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_requires_authentication_when_reads_are_private(self):
        self.assertEqual(self.zones().status_code, status.HTTP_401_UNAUTHORIZED)
