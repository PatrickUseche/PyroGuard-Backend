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
