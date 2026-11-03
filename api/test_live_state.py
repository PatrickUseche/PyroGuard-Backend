"""Pruebas del estado en memoria de las lecturas (buffer reciente, ventana y cachés)."""
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Node, SensorReading
from .services.live_readings import live_readings


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


class LiveStateTestCase(APITestCase):
    """Base: el estado en memoria es global al proceso, así que se limpia en cada prueba."""

    def setUp(self):
        live_readings.clear()
        self.addCleanup(live_readings.clear)
        self.node = Node.objects.create(node_id="NODE-001")
        self.base_time = timezone.now() - timedelta(hours=1)

    def create_reading(self, minute, temperature=25.0, node=None):
        return SensorReading.objects.create(
            node=node or self.node,
            temperature=temperature,
            humidity=40.0,
            smoke=10,
            flame=False,
            timestamp=self.base_time + timedelta(minutes=minute),
        )

    def ingest(self, minute, temperature=25.0, node_id="NODE-001"):
        return self.client.post(
            reverse("receive_reading"),
            {
                "node_id": node_id,
                "temperature": temperature,
                "humidity": 40.0,
                "smoke": 10,
                "flame": False,
                "timestamp": (self.base_time + timedelta(minutes=minute)).isoformat(),
            },
            format="json",
            HTTP_X_API_KEY=INGEST_KEY,
        )


@override_settings(INGEST_API_KEY=INGEST_KEY, RECENT_READINGS_PER_NODE=3)
class RecentReadingsStoreTests(LiveStateTestCase):
    def test_first_query_loads_the_latest_readings_from_the_database(self):
        for minute in range(5):
            self.create_reading(minute, temperature=20 + minute)

        recent = live_readings.recent(self.node)

        self.assertEqual([r["temperature"] for r in recent], [24.0, 23.0, 22.0])
        self.assertTrue(live_readings.is_loaded("NODE-001"))

    def test_a_loaded_node_is_served_without_querying_the_database(self):
        self.create_reading(0)
        live_readings.recent(self.node)

        with self.assertNumQueries(0):
            live_readings.recent(self.node)

    def test_a_node_without_readings_loads_as_empty_and_stays_loaded(self):
        self.assertEqual(live_readings.recent(self.node), [])

        with self.assertNumQueries(0):
            self.assertEqual(live_readings.recent(self.node), [])

    def test_ingestion_does_not_buffer_a_node_nobody_has_queried(self):
        self.assertEqual(self.ingest(0).status_code, status.HTTP_201_CREATED)

        self.assertFalse(live_readings.is_loaded("NODE-001"))

    def test_ingestion_updates_a_loaded_buffer(self):
        live_readings.recent(self.node)

        self.ingest(0, temperature=30)
        self.ingest(1, temperature=31)

        recent = live_readings.recent(self.node)
        self.assertEqual([r["temperature"] for r in recent], [31.0, 30.0])

    def test_the_buffer_keeps_only_the_latest_n(self):
        live_readings.recent(self.node)

        for minute in range(5):
            self.ingest(minute, temperature=20 + minute)

        recent = live_readings.recent(self.node)
        self.assertEqual([r["temperature"] for r in recent], [24.0, 23.0, 22.0])

    def test_buffered_readings_include_the_risk_level(self):
        live_readings.recent(self.node)

        self.ingest(0, temperature=25)

        self.assertEqual(live_readings.recent(self.node)[0]["risk_level"], "NORMAL")

    def test_limit_cuts_the_result(self):
        for minute in range(3):
            self.create_reading(minute, temperature=20 + minute)

        self.assertEqual(len(live_readings.recent(self.node, limit=2)), 2)

    def test_nodes_do_not_share_buffers(self):
        other = Node.objects.create(node_id="NODE-002")
        self.create_reading(0, temperature=11)
        self.create_reading(0, temperature=22, node=other)

        self.assertEqual(live_readings.recent(self.node)[0]["temperature"], 11.0)
        self.assertEqual(live_readings.recent(other)[0]["temperature"], 22.0)

    def test_clear_forgets_every_node(self):
        live_readings.recent(self.node)

        live_readings.clear()

        self.assertFalse(live_readings.is_loaded("NODE-001"))

    def test_a_failure_while_buffering_does_not_lose_the_reading(self):
        live_readings.recent(self.node)

        with patch.object(live_readings, "record", side_effect=RuntimeError("fallo")):
            with self.assertLogs("api.readings", level="ERROR"):
                response = self.ingest(0)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 1)


@override_settings(INGEST_API_KEY=INGEST_KEY, RECENT_READINGS_PER_NODE=3)
class RecentReadingsEndpointTests(LiveStateTestCase):
    def url(self, node_id="NODE-001"):
        return reverse("node_recent_readings", kwargs={"node_id": node_id})

    def test_returns_the_latest_readings_newest_first(self):
        for minute in range(5):
            self.create_reading(minute, temperature=20 + minute)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([r["temperature"] for r in response.data], [24.0, 23.0, 22.0])
        self.assertEqual(response.data[0]["node_id"], "NODE-001")

    def test_returns_the_same_fields_as_the_readings_endpoint(self):
        self.create_reading(0)

        response = self.client.get(self.url())

        self.assertEqual(
            set(response.data[0]),
            {"node_id", "temperature", "humidity", "smoke", "gas", "flame",
             "timestamp", "risk_level", "ai"},
        )

    def test_second_request_does_not_touch_the_database_for_readings(self):
        self.create_reading(0)
        self.client.get(self.url())

        with self.assertNumQueries(1):  # solo la comprobación de que el nodo existe
            self.client.get(self.url())

    def test_reflects_readings_ingested_after_the_first_request(self):
        self.client.get(self.url())

        self.ingest(0, temperature=33)

        response = self.client.get(self.url())
        self.assertEqual([r["temperature"] for r in response.data], [33.0])

    def test_unknown_node_returns_404(self):
        response = self.client.get(self.url("NO-EXISTE"))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_node_without_readings_returns_an_empty_list(self):
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_limit_parameter(self):
        for minute in range(3):
            self.create_reading(minute, temperature=20 + minute)

        response = self.client.get(self.url(), {"limit": 2})

        self.assertEqual([r["temperature"] for r in response.data], [22.0, 21.0])

    def test_invalid_limit_is_rejected(self):
        for limit in ("0", "4", "-1", "abc", "1.5"):
            with self.subTest(limit=limit):
                response = self.client.get(self.url(), {"limit": limit})

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_requires_authentication_when_reads_are_private(self):
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
