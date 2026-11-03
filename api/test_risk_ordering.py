"""Pruebas del orden de urgencia de alertas y del top-K de nodos por riesgo."""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Alert, Node, RiskAssessment, SensorReading
from .services.alert_ordering import most_urgent, order_by_urgency, urgency
from .services.dashboard_cache import dashboard_cache

_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "login": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


def fake_alert(pk, level, minutes_ago):
    created = datetime(2026, 10, 30, 12, 0, tzinfo=dt_timezone.utc) - timedelta(minutes=minutes_ago)
    return SimpleNamespace(pk=pk, level=level, created_at=created)


class AlertOrderingTests(SimpleTestCase):
    def test_fire_comes_before_warning(self):
        alerts = [fake_alert(1, "WARNING", 60), fake_alert(2, "FIRE", 1)]

        self.assertEqual([a.pk for a in order_by_urgency(alerts)], [2, 1])

    def test_with_the_same_level_the_oldest_comes_first(self):
        alerts = [fake_alert(1, "FIRE", 5), fake_alert(2, "FIRE", 50), fake_alert(3, "FIRE", 20)]

        self.assertEqual([a.pk for a in order_by_urgency(alerts)], [2, 3, 1])

    def test_ties_are_broken_by_pk(self):
        alerts = [fake_alert(9, "FIRE", 5), fake_alert(4, "FIRE", 5), fake_alert(7, "FIRE", 5)]

        self.assertEqual([a.pk for a in order_by_urgency(alerts)], [4, 7, 9])

    def test_severity_beats_age(self):
        alerts = [
            fake_alert(1, "WARNING", 1000),
            fake_alert(2, "FIRE", 1),
            fake_alert(3, "WARNING", 500),
            fake_alert(4, "FIRE", 10),
        ]

        self.assertEqual([a.pk for a in order_by_urgency(alerts)], [4, 2, 1, 3])

    def test_empty_list(self):
        self.assertEqual(order_by_urgency([]), [])
        self.assertEqual(most_urgent([], 3), [])

    def test_most_urgent_returns_only_k(self):
        alerts = [fake_alert(1, "WARNING", 9), fake_alert(2, "FIRE", 3), fake_alert(3, "FIRE", 8)]

        self.assertEqual([a.pk for a in most_urgent(alerts, 2)], [3, 2])

    def test_it_matches_a_plain_sort(self):
        alerts = [
            fake_alert(pk, level, minutes)
            for pk, (level, minutes) in enumerate(
                [("WARNING", 3), ("FIRE", 3), ("FIRE", 7), ("WARNING", 1), ("FIRE", 3)], start=1
            )
        ]

        self.assertEqual(order_by_urgency(alerts), sorted(alerts, key=urgency))

    def test_an_unknown_level_goes_last(self):
        alerts = [fake_alert(1, "OTRO", 100), fake_alert(2, "WARNING", 1)]

        self.assertEqual([a.pk for a in order_by_urgency(alerts)], [2, 1])


class RiskApiTestCase(APITestCase):
    def setUp(self):
        dashboard_cache.clear()
        self.addCleanup(dashboard_cache.clear)
        self.counter = 0

    def make_node(self, node_id, risk=None, probability=None, offline=False):
        node = Node.objects.create(
            node_id=node_id,
            last_communication=timezone.now() - timedelta(hours=5 if offline else 0, seconds=1),
        )
        if risk:
            self.assess(node, risk, probability)
        return node

    def assess(self, node, risk, probability=None):
        self.counter += 1
        reading = SensorReading.objects.create(
            node=node,
            temperature=20,
            humidity=40,
            smoke=1,
            flame=False,
            timestamp=timezone.now() - timedelta(seconds=100 - self.counter),
        )
        assessment = RiskAssessment.objects.create(
            reading=reading, risk_level=risk, ai_probability=probability, rule_reasons=[]
        )
        return reading, assessment

    def make_alert(self, node, level, minutes_ago, alert_status=Alert.Status.ACTIVE):
        reading, assessment = self.assess(node, level)
        alert = Alert.objects.create(
            node=node, reading=reading, assessment=assessment, level=level,
            message="prueba", status=alert_status,
        )
        Alert.objects.filter(pk=alert.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago)
        )
        return alert


class ActiveAlertsOrderTests(RiskApiTestCase):
    def active(self):
        return self.client.get(reverse("active_alerts"))

    def test_active_alerts_come_most_urgent_first(self):
        warning_old = self.make_alert(self.make_node("N1"), "WARNING", 300)
        fire_new = self.make_alert(self.make_node("N2"), "FIRE", 2)
        fire_old = self.make_alert(self.make_node("N3"), "FIRE", 90)
        warning_new = self.make_alert(self.make_node("N4"), "WARNING", 5)

        response = self.active()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [a["id"] for a in response.data],
            [fire_old.pk, fire_new.pk, warning_old.pk, warning_new.pk],
        )

    def test_closed_alerts_are_not_listed_and_acknowledged_ones_are(self):
        active = self.make_alert(self.make_node("N1"), "FIRE", 10)
        acknowledged = self.make_alert(
            self.make_node("N2"), "FIRE", 20, alert_status=Alert.Status.ACKNOWLEDGED
        )
        self.make_alert(self.make_node("N3"), "FIRE", 30, alert_status=Alert.Status.CLOSED)

        ids = [a["id"] for a in self.active().data]

        self.assertEqual(ids, [acknowledged.pk, active.pk])

    def test_no_alerts_returns_an_empty_list(self):
        self.assertEqual(self.active().data, [])

    def test_the_alert_history_keeps_newest_first(self):
        old = self.make_alert(self.make_node("N1"), "FIRE", 90)
        new = self.make_alert(self.make_node("N2"), "WARNING", 5)

        ids = [a["id"] for a in self.client.get(reverse("alert_list")).data]

        self.assertEqual(ids, [new.pk, old.pk])


class TopRiskNodesTests(RiskApiTestCase):
    def top(self, **params):
        return self.client.get(reverse("dashboard_top_risk"), params)

    def test_orders_by_risk_level(self):
        self.make_node("A-NORMAL", "NORMAL")
        self.make_node("B-FIRE", "FIRE")
        self.make_node("C-WARNING", "WARNING")

        ids = [n["node_id"] for n in self.top().data]

        self.assertEqual(ids, ["B-FIRE", "C-WARNING", "A-NORMAL"])

    def test_same_level_orders_by_ai_probability(self):
        self.make_node("N1", "WARNING", 0.4)
        self.make_node("N2", "WARNING", 0.9)
        self.make_node("N3", "WARNING", None)
        self.make_node("N4", "WARNING", 0.6)

        ids = [n["node_id"] for n in self.top().data]

        self.assertEqual(ids, ["N2", "N4", "N1", "N3"])

    def test_same_level_and_probability_orders_by_node_id(self):
        self.make_node("N-C", "FIRE", 0.5)
        self.make_node("N-A", "FIRE", 0.5)
        self.make_node("N-B", "FIRE", 0.5)

        ids = [n["node_id"] for n in self.top().data]

        self.assertEqual(ids, ["N-A", "N-B", "N-C"])

    def test_k_limits_the_result(self):
        for number in range(8):
            self.make_node(f"N{number}", "FIRE", number / 10)

        response = self.top(k=3)

        self.assertEqual([n["node_id"] for n in response.data], ["N7", "N6", "N5"])

    def test_default_k_is_five(self):
        for number in range(8):
            self.make_node(f"N{number}", "WARNING")

        self.assertEqual(len(self.top().data), 5)

    def test_k_larger_than_the_nodes_returns_them_all(self):
        self.make_node("N1", "FIRE")

        self.assertEqual(len(self.top(k=50).data), 1)

    def test_invalid_k_is_rejected(self):
        for k in ("0", "51", "-1", "abc", "2.5"):
            with self.subTest(k=k):
                self.assertEqual(self.top(k=k).status_code, status.HTTP_400_BAD_REQUEST)

    def test_nodes_without_an_assessment_are_left_out(self):
        self.make_node("SIN-LECTURAS")
        self.make_node("CON-RIESGO", "WARNING")

        ids = [n["node_id"] for n in self.top().data]

        self.assertEqual(ids, ["CON-RIESGO"])

    def test_only_the_latest_assessment_counts(self):
        node = self.make_node("N1", "FIRE")
        self.assess(node, "NORMAL", 0.1)
        other = self.make_node("N2", "WARNING")

        response = self.top()

        self.assertEqual([n["node_id"] for n in response.data], ["N2", "N1"])
        self.assertEqual(response.data[1]["current_risk"], "NORMAL")
        self.assertEqual(response.data[1]["ai_probability"], 0.1)
        self.assertEqual(other.node_id, "N2")

    def test_an_offline_node_keeps_its_last_risk_and_is_flagged_stale(self):
        self.make_node("OFFLINE-FIRE", "FIRE", offline=True)
        self.make_node("ONLINE-WARNING", "WARNING")

        response = self.top()

        first, second = response.data
        self.assertEqual(first["node_id"], "OFFLINE-FIRE")
        self.assertEqual(first["connection_status"], "OFFLINE")
        self.assertTrue(first["current_risk_stale"])
        self.assertEqual(second["connection_status"], "ONLINE")
        self.assertFalse(second["current_risk_stale"])

    def test_each_node_has_the_documented_fields(self):
        self.make_node("N1", "FIRE", 0.8)

        self.assertEqual(
            set(self.top().data[0]),
            {"node_id", "name", "current_risk", "ai_probability", "connection_status",
             "current_risk_stale", "last_communication"},
        )

    def test_no_nodes_returns_an_empty_list(self):
        response = self.top()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_it_matches_a_plain_sort_on_many_nodes(self):
        risks = ["NORMAL", "WARNING", "FIRE"]
        expected = []
        for number in range(30):
            risk = risks[number % 3]
            probability = ((number * 7) % 10) / 10
            self.make_node(f"N{number:02d}", risk, probability)
            expected.append((-(risks.index(risk) + 1), -probability, f"N{number:02d}"))

        ids = [n["node_id"] for n in self.top(k=10).data]

        self.assertEqual(ids, [item[2] for item in sorted(expected)[:10]])

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_requires_authentication_when_reads_are_private(self):
        self.assertEqual(self.top().status_code, status.HTTP_401_UNAUTHORIZED)
