"""Fallos parciales de la ingesta: qué se conserva y qué se propaga."""
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Node, SensorReading

INGEST_KEY = "clave-ingesta-pruebas"


@override_settings(INGEST_API_KEY=INGEST_KEY, AI_SERVICE_URL="")
class LastCommunicationFailureTests(APITestCase):
    def test_the_reading_is_kept_when_the_node_update_fails(self):
        Node.objects.create(node_id="ING-1")
        payload = {
            "node_id": "ING-1", "temperature": 22, "humidity": 60, "smoke": 5, "gas": 0, "flame": False,
            "timestamp": timezone.now().isoformat(),
        }
        # Solo el `Node` que ve la ingesta: el serializer sigue validando el nodo contra la base real.
        broken_node = MagicMock()
        broken_node.objects.filter.return_value.update.side_effect = RuntimeError("bloqueo")
        with (
            patch("api.services.ingestion.Node", broken_node),
            self.assertLogs("api.readings", level="ERROR") as logs,
        ):
            response = self.client.post(reverse("receive_reading"), payload, format="json", HTTP_X_API_KEY=INGEST_KEY)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(SensorReading.objects.filter(node__node_id="ING-1").count(), 1)
        self.assertIsNone(Node.objects.get(node_id="ING-1").last_communication)
        self.assertIn("se conserva la lectura", " ".join(logs.output))
