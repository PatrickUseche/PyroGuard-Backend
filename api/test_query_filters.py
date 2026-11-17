"""Validación de los filtros de fecha, rango y orden de `/readings/` y `/alerts/`."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Alert, Node, SensorReading


class ReadingFilterValidationTests(APITestCase):
    def setUp(self):
        Node.objects.create(node_id="NODE-F1")

    def get(self, **params):
        return self.client.get(reverse("receive_reading"), params)

    def test_an_impossible_date_is_a_bad_request(self):
        for parameter in ("from", "to"):
            with self.subTest(parameter=parameter), self.assertLogs("api.readings", level="WARNING"):
                response = self.get(**{parameter: "2026-13-45T10:00:00Z"})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("ISO 8601", str(response.data))

    def test_an_unknown_range_is_a_bad_request(self):
        with self.assertLogs("api.readings", level="WARNING"):
            response = self.get(range="30d")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("'24h' o '7d'", str(response.data))

    def test_an_unknown_order_is_a_bad_request(self):
        with self.assertLogs("api.readings", level="WARNING"):
            response = self.get(order="random")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("'asc' o 'desc'", str(response.data))

    def test_valid_range_and_order_are_accepted(self):
        for params in ({"range": "24h"}, {"range": "7d", "order": "asc"}, {"order": "desc"}):
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, status.HTTP_200_OK)


class AlertFilterTests(APITestCase):
    def setUp(self):
        self.now = timezone.now()
        self.north = Node.objects.create(node_id="NORTE-1")
        self.south = Node.objects.create(node_id="SUR-1")
        self.old = self.alert(self.north, days_ago=10)
        self.recent_north = self.alert(self.north, days_ago=1)
        self.recent_south = self.alert(self.south, days_ago=1)

    def alert(self, node, days_ago):
        created = self.now - timedelta(days=days_ago)
        reading = SensorReading.objects.create(
            node=node, temperature=40, humidity=20, smoke=300, gas=0, flame=False, timestamp=created
        )
        alert = Alert.objects.create(node=node, reading=reading, level=Alert.Level.WARNING, message="prueba")
        Alert.objects.filter(pk=alert.pk).update(created_at=created)
        return alert

    def ids(self, **params):
        response = self.client.get(reverse("alert_list"), params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return {item["id"] for item in response.data}

    def test_filter_by_node_id(self):
        self.assertEqual(self.ids(node_id="NORTE-1"), {self.old.pk, self.recent_north.pk})

    def test_filter_by_date_range(self):
        since = (self.now - timedelta(days=2)).isoformat()
        until = (self.now - timedelta(days=5)).isoformat()
        self.assertEqual(self.ids(**{"from": since}), {self.recent_north.pk, self.recent_south.pk})
        self.assertEqual(self.ids(to=until), {self.old.pk})

    def test_node_and_dates_combine(self):
        since = (self.now - timedelta(days=2)).isoformat()
        self.assertEqual(self.ids(node_id="NORTE-1", **{"from": since}), {self.recent_north.pk})

    def test_from_after_to_is_a_bad_request(self):
        params = {"from": self.now.isoformat(), "to": (self.now - timedelta(days=1)).isoformat()}
        response = self.client.get(reverse("alert_list"), params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("posterior", str(response.data))

    def test_an_invalid_date_is_a_bad_request(self):
        response = self.client.get(reverse("alert_list"), {"to": "ayer"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_by_status_and_level(self):
        Alert.objects.filter(pk=self.old.pk).update(status=Alert.Status.CLOSED, level=Alert.Level.FIRE)
        self.assertEqual(self.ids(status=Alert.Status.CLOSED), {self.old.pk})
        self.assertEqual(self.ids(level=Alert.Level.FIRE), {self.old.pk})
        self.assertEqual(self.ids(level=Alert.Level.WARNING), {self.recent_north.pk, self.recent_south.pk})
        self.assertEqual(self.ids(status=Alert.Status.CLOSED, level=Alert.Level.WARNING), set())
