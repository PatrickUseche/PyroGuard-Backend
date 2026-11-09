"""Pruebas de las cachés en memoria: estado de nodos y resumen del dashboard."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Alert, Node, RiskAssessment, SensorReading
from .services.dashboard_cache import DashboardSummaryCache, dashboard_cache
from .services.live_readings import live_readings
from .services.node_status_cache import NodeStatusCache, node_status_cache

_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "google_login": None, "google_register": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


INGEST_KEY = "test-ingest-key"


class CacheTestCase(APITestCase):
    def setUp(self):
        for cache in (live_readings, node_status_cache, dashboard_cache):
            cache.clear()
            self.addCleanup(cache.clear)
        self.node = Node.objects.create(node_id="NODE-001")

    def status_url(self, node_id="NODE-001"):
        return reverse("node_status", kwargs={"node_id": node_id})

    def ingest(self, temperature=25.0, smoke=10, flame=False, node_id="NODE-001"):
        return self.client.post(
            reverse("receive_reading"),
            {
                "node_id": node_id,
                "temperature": temperature,
                "humidity": 40.0,
                "smoke": smoke,
                "flame": flame,
                "timestamp": timezone.now().isoformat(),
            },
            format="json",
            HTTP_X_API_KEY=INGEST_KEY,
        )

    def login(self):
        user = get_user_model().objects.create_user("operador", password="clave-segura-1")
        user.groups.add(Group.objects.get(name="Operadores"))
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")


class NodeStatusCacheUnitTests(SimpleTestCase):
    @override_settings(NODE_STATUS_CACHE_SIZE=2)
    def test_stores_and_returns_copies(self):
        cache = NodeStatusCache()
        cache.put("a", {"alerts": [1]})

        first = cache.get("a")
        first["alerts"].append(2)

        self.assertEqual(cache.get("a"), {"alerts": [1]})

    @override_settings(NODE_STATUS_CACHE_SIZE=2)
    def test_evicts_the_least_recently_used_node(self):
        cache = NodeStatusCache()
        cache.put("a", {"n": 1})
        cache.put("b", {"n": 2})
        cache.get("a")  # «b» pasa a ser el menos usado

        cache.put("c", {"n": 3})

        self.assertIsNone(cache.get("b"))
        self.assertIsNotNone(cache.get("a"))
        self.assertIsNotNone(cache.get("c"))
        self.assertEqual(cache.stats["size"], 2)

    @override_settings(NODE_STATUS_CACHE_SIZE=2)
    def test_invalidate_and_clear(self):
        cache = NodeStatusCache()
        cache.put("a", {"n": 1})
        cache.put("b", {"n": 2})

        cache.invalidate("a")
        cache.invalidate("desconocido")
        self.assertIsNone(cache.get("a"))
        self.assertIsNotNone(cache.get("b"))

        cache.clear()
        self.assertIsNone(cache.get("b"))

    @override_settings(NODE_STATUS_CACHE_SIZE=0)
    def test_size_zero_disables_the_cache(self):
        cache = NodeStatusCache()

        cache.put("a", {"n": 1})

        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.stats["size"], 0)

    def test_a_new_capacity_creates_a_new_cache(self):
        cache = NodeStatusCache()
        with override_settings(NODE_STATUS_CACHE_SIZE=1):
            cache.put("a", {"n": 1})
        with override_settings(NODE_STATUS_CACHE_SIZE=5):
            self.assertIsNone(cache.get("a"))

    @override_settings(NODE_STATUS_CACHE_SIZE=3)
    def test_counts_hits_and_misses(self):
        cache = NodeStatusCache()
        cache.get("a")
        cache.put("a", {"n": 1})
        cache.get("a")

        self.assertEqual(cache.stats["hits"], 1)
        self.assertEqual(cache.stats["misses"], 1)


@override_settings(INGEST_API_KEY=INGEST_KEY, NODE_STATUS_CACHE_SIZE=2, TEMPERATURE_WINDOW_SIZE=5)
class NodeStatusCacheEndpointTests(CacheTestCase):
    def test_second_request_is_served_without_queries(self):
        self.client.get(self.status_url())

        with self.assertNumQueries(0):
            response = self.client.get(self.status_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["node_id"], "NODE-001")

    def test_cached_and_fresh_responses_are_identical(self):
        self.ingest()
        fresh = self.client.get(self.status_url()).data

        cached = self.client.get(self.status_url()).data

        self.assertEqual(cached, fresh)

    def test_ingestion_invalidates_the_node(self):
        first = self.client.get(self.status_url()).data
        self.assertIsNone(first["latest_reading"])

        self.ingest(temperature=31)

        second = self.client.get(self.status_url()).data
        self.assertEqual(second["latest_reading"]["temperature"], 31.0)
        self.assertEqual(second["current_risk"], "NORMAL")
        self.assertEqual(second["connection_status"], "ONLINE")

    def test_ingestion_of_one_node_keeps_the_others_cached(self):
        Node.objects.create(node_id="NODE-002")
        self.client.get(self.status_url("NODE-002"))

        self.ingest()

        with self.assertNumQueries(0):
            self.client.get(self.status_url("NODE-002"))

    @override_settings(INGEST_API_KEY=INGEST_KEY)
    def test_a_new_alert_updates_the_cached_count(self):
        self.client.get(self.status_url())

        self.ingest(temperature=90, smoke=900, flame=True)

        self.assertEqual(self.client.get(self.status_url()).data["active_alerts_count"], 1)
        self.assertEqual(self.client.get(self.status_url()).data["current_risk"], "FIRE")

    def test_closing_an_alert_invalidates_the_node(self):
        self.ingest(temperature=90, smoke=900, flame=True)
        self.assertEqual(self.client.get(self.status_url()).data["active_alerts_count"], 1)
        alert = Alert.objects.get()
        self.login()

        response = self.client.post(reverse("alert_close", kwargs={"alert_id": alert.pk}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(self.status_url()).data["active_alerts_count"], 0)

    def test_deleting_the_node_invalidates_it(self):
        self.client.get(self.status_url())

        self.node.delete()

        self.assertEqual(self.client.get(self.status_url()).status_code, status.HTTP_404_NOT_FOUND)

    def test_connection_status_follows_the_clock_even_on_a_cache_hit(self):
        Node.objects.filter(pk=self.node.pk).update(last_communication=timezone.now())
        with override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=60):
            self.assertEqual(self.client.get(self.status_url()).data["connection_status"], "ONLINE")

            later = timezone.now() + timedelta(seconds=120)
            with patch("api.models.timezone.now", return_value=later):
                with self.assertNumQueries(0):
                    data = self.client.get(self.status_url()).data

        self.assertEqual(data["connection_status"], "OFFLINE")
        self.assertTrue(data["current_risk_stale"])

    def test_capacity_evicts_the_least_recently_used_node(self):
        for number in (2, 3):
            Node.objects.create(node_id=f"NODE-00{number}")
        for node_id in ("NODE-001", "NODE-002", "NODE-003"):
            self.client.get(self.status_url(node_id))

        self.assertEqual(node_status_cache.stats["size"], 2)
        with self.assertNumQueries(0):
            self.client.get(self.status_url("NODE-003"))
        with self.assertRaises(AssertionError):
            with self.assertNumQueries(0):
                self.client.get(self.status_url("NODE-001"))

    @override_settings(NODE_STATUS_CACHE_SIZE=0)
    def test_disabled_cache_always_queries(self):
        self.client.get(self.status_url())

        with self.assertRaises(AssertionError):
            with self.assertNumQueries(0):
                self.client.get(self.status_url())

    def test_unknown_node_is_not_cached(self):
        self.assertEqual(self.client.get(self.status_url("NO-EXISTE")).status_code, 404)
        self.assertEqual(node_status_cache.stats["size"], 0)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@override_settings(DASHBOARD_CACHE_SECONDS=5)
class DashboardSummaryCacheUnitTests(SimpleTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.cache = DashboardSummaryCache(clock=self.clock)

    def test_returns_none_when_empty(self):
        self.assertIsNone(self.cache.get())

    def test_returns_a_copy_while_valid(self):
        self.cache.put({"nodes": [1]})

        first = self.cache.get()
        first["nodes"].append(2)

        self.assertEqual(self.cache.get(), {"nodes": [1]})

    def test_expires_after_the_configured_seconds(self):
        self.cache.put({"total": 1})

        self.clock.now += 4.9
        self.assertIsNotNone(self.cache.get())
        self.clock.now += 0.2
        self.assertIsNone(self.cache.get())

    def test_invalidate_discards_the_summary(self):
        self.cache.put({"total": 1})

        self.cache.invalidate()

        self.assertIsNone(self.cache.get())

    def test_a_new_summary_restarts_the_clock(self):
        self.cache.put({"total": 1})
        self.clock.now += 4
        self.cache.put({"total": 2})
        self.clock.now += 4

        self.assertEqual(self.cache.get(), {"total": 2})

    @override_settings(DASHBOARD_CACHE_SECONDS=0)
    def test_zero_seconds_disables_it(self):
        self.cache.put({"total": 1})

        self.assertIsNone(self.cache.get())


@override_settings(INGEST_API_KEY=INGEST_KEY, DASHBOARD_CACHE_SECONDS=5)
class DashboardSummaryCacheEndpointTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        patcher = patch.object(dashboard_cache, "_clock", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def summary(self):
        return self.client.get(reverse("dashboard_summary")).data

    def test_second_request_is_served_without_queries(self):
        first = self.summary()

        with self.assertNumQueries(0):
            second = self.summary()

        self.assertEqual(first, second)
        self.assertEqual(first["total_nodes"], 1)

    def test_it_is_rebuilt_after_it_expires(self):
        self.summary()
        self.clock.now += 6

        with self.assertRaises(AssertionError):
            with self.assertNumQueries(0):
                self.summary()

    def test_ingestion_invalidates_it(self):
        self.assertEqual(self.summary()["latest_readings"], [])

        self.ingest(temperature=33)

        summary = self.summary()
        self.assertEqual(len(summary["latest_readings"]), 1)
        self.assertEqual(summary["latest_readings"][0]["temperature"], 33.0)

    def test_a_new_node_invalidates_it(self):
        self.assertEqual(self.summary()["total_nodes"], 1)

        Node.objects.create(node_id="NODE-002")

        self.assertEqual(self.summary()["total_nodes"], 2)

    def test_a_new_alert_invalidates_it(self):
        self.assertEqual(self.summary()["active_alerts"], 0)

        self.ingest(temperature=90, smoke=900, flame=True)

        summary = self.summary()
        self.assertEqual(summary["active_alerts"], 1)
        self.assertEqual(summary["overall_risk"], "FIRE")

    def test_deleting_a_node_invalidates_it(self):
        self.summary()

        self.node.delete()

        self.assertEqual(self.summary()["total_nodes"], 0)

    @override_settings(DASHBOARD_CACHE_SECONDS=0)
    def test_disabled_cache_always_queries(self):
        self.summary()

        with self.assertRaises(AssertionError):
            with self.assertNumQueries(0):
                self.summary()

    def test_a_reading_assessment_change_invalidates_it(self):
        reading = SensorReading.objects.create(
            node=self.node, temperature=20, humidity=40, smoke=5, flame=False
        )
        self.summary()

        RiskAssessment.objects.create(
            reading=reading, risk_level="WARNING", rule_reasons=[]
        )

        self.assertEqual(len(self.summary()["latest_readings"]), 1)
        self.assertEqual(self.summary()["latest_readings"][0]["risk_level"], "WARNING")
