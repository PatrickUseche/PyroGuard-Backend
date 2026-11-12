"""Pruebas de la detección de lecturas duplicadas en la ingesta."""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Alert, Node, SensorReading
from .services.duplicate_readings import duplicate_readings
from .services.live_readings import live_readings
from .services.node_status_cache import node_status_cache

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
MOMENT = datetime(2026, 10, 30, 12, 0, 0, 123456, tzinfo=dt_timezone.utc)


@override_settings(INGEST_API_KEY=INGEST_KEY)
class DuplicateReadingTests(APITestCase):
    def setUp(self):
        for state in (duplicate_readings, live_readings, node_status_cache):
            state.clear()
            self.addCleanup(state.clear)
        self.node = Node.objects.create(node_id="NODE-001")
        Node.objects.create(node_id="NODE-002")

    def post(self, timestamp=MOMENT, node_id="NODE-001", **overrides):
        payload = {
            "node_id": node_id,
            "temperature": 25.0,
            "humidity": 40.0,
            "smoke": 10,
            "flame": False,
            "timestamp": timestamp if isinstance(timestamp, str) else timestamp.isoformat(),
            **overrides,
        }
        return self.client.post(
            reverse("receive_reading"), payload, format="json", HTTP_X_API_KEY=INGEST_KEY
        )

    def test_a_new_reading_is_created(self):
        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(SensorReading.objects.count(), 1)

    def test_the_same_reading_twice_is_stored_once(self):
        first = self.post()

        second = self.post()

        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["status"], "duplicate")
        self.assertIsNone(second.data["alert_id"])
        self.assertEqual(second.data["reading"], first.data["reading"])
        self.assertEqual(second.data["risk_level"], first.data["risk_level"])
        self.assertEqual(SensorReading.objects.count(), 1)

    def test_a_duplicate_with_different_values_is_still_a_duplicate(self):
        self.post(temperature=25)

        response = self.post(temperature=80)

        self.assertEqual(response.data["status"], "duplicate")
        self.assertEqual(SensorReading.objects.get().temperature, 25.0)

    def test_the_same_instant_in_another_time_zone_is_a_duplicate(self):
        self.post(timestamp="2026-10-30T12:00:00.123456Z")

        response = self.post(timestamp="2026-10-30T14:00:00.123456+02:00")

        self.assertEqual(response.data["status"], "duplicate")
        self.assertEqual(SensorReading.objects.count(), 1)

    def test_a_duplicate_does_not_create_another_alert_or_occurrence(self):
        self.post(temperature=90, smoke=900, flame=True)
        alert = Alert.objects.get()

        self.post(temperature=90, smoke=900, flame=True)

        alert.refresh_from_db()
        self.assertEqual(Alert.objects.count(), 1)
        self.assertEqual(alert.occurrences, 1)

    def test_the_same_timestamp_on_another_node_is_not_a_duplicate(self):
        self.post(node_id="NODE-001")

        response = self.post(node_id="NODE-002")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 2)

    def test_another_timestamp_on_the_same_node_is_not_a_duplicate(self):
        self.post()

        response = self.post(timestamp=MOMENT + timedelta(microseconds=1))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 2)

    def test_a_bloom_false_positive_is_confirmed_in_the_database_and_saved(self):
        # El filtro cree que ya la vio, pero en la base no existe: no se descarta.
        duplicate_readings.remember("NODE-001", MOMENT)

        response = self.post()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 1)

    def test_invalid_readings_are_rejected_before_looking_for_duplicates(self):
        self.post()

        response = self.post(temperature=999)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_after_a_restart_duplicates_of_stored_readings_are_still_found(self):
        self.post()
        duplicate_readings.clear()  # como al reiniciar el proceso: el filtro queda vacío

        response = self.post()

        self.assertEqual(response.data["status"], "duplicate")
        self.assertEqual(SensorReading.objects.count(), 1)

    def test_the_filter_is_not_consulted_for_a_new_reading_in_the_database(self):
        self.post()

        with patch.object(SensorReading.objects, "filter", wraps=SensorReading.objects.filter) as lookup:
            duplicate_readings.find("NODE-001", MOMENT + timedelta(seconds=5))

        lookup.assert_not_called()

    @override_settings(DEDUPLICATE_READINGS=False)
    def test_turning_the_filter_off_still_cannot_store_a_duplicate(self):
        self.post()

        response = self.post()

        # Sin filtro la barrera es la restricción única de la base de datos.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "duplicate")
        self.assertEqual(SensorReading.objects.count(), 1)

    @override_settings(DUPLICATE_FILTER_CAPACITY=4)
    def test_the_filter_is_rebuilt_when_it_fills_up_and_keeps_detecting_recent_duplicates(self):
        for second in range(6):
            self.assertEqual(
                self.post(timestamp=MOMENT + timedelta(seconds=second)).status_code,
                status.HTTP_201_CREATED,
            )

        latest = self.post(timestamp=MOMENT + timedelta(seconds=5))

        self.assertEqual(latest.data["status"], "duplicate")
        self.assertEqual(SensorReading.objects.count(), 6)

    def test_a_ingested_duplicate_does_not_touch_the_node_communication(self):
        self.post()
        self.node.refresh_from_db()
        first_contact = self.node.last_communication

        self.post()

        self.node.refresh_from_db()
        self.assertEqual(self.node.last_communication, first_contact)


@override_settings(INGEST_API_KEY=INGEST_KEY)
class DatabaseUniquenessTests(APITestCase):
    """La base rechaza el duplicado aunque el filtro en memoria no lo conozca."""

    def setUp(self):
        for state in (duplicate_readings, live_readings, node_status_cache):
            state.clear()
        self.node = Node.objects.create(node_id="NODE-001")

    def test_database_rejects_same_node_and_timestamp(self):
        from django.db import IntegrityError, transaction

        values = {"temperature": 25, "humidity": 40, "smoke": 1, "timestamp": MOMENT}
        SensorReading.objects.create(node=self.node, **values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SensorReading.objects.create(node=self.node, **values)

    def test_race_is_answered_as_duplicate_not_as_error(self):
        existing = SensorReading.objects.create(
            node=self.node, temperature=25, humidity=40, smoke=1, timestamp=MOMENT
        )
        # El filtro no conoce la lectura (como en otro worker o tras un reinicio).
        with patch.object(duplicate_readings, "find", return_value=None):
            response = self.client.post(
                reverse("receive_reading"),
                {
                    "node_id": "NODE-001",
                    "temperature": 25,
                    "humidity": 40,
                    "smoke": 1,
                    "flame": False,
                    "timestamp": MOMENT.isoformat(),
                },
                format="json",
                HTTP_X_API_KEY=INGEST_KEY,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "duplicate")
        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertEqual(SensorReading.objects.get().pk, existing.pk)
