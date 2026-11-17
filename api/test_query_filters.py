"""Validación de los filtros de fecha, rango y orden de `/readings/` y `/alerts/`."""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Node


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
