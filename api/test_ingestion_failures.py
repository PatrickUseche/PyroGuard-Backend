"""Fallos parciales de la ingesta: qué se conserva y qué se propaga."""
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Node, SensorReading
from .services.ingestion import ingest_reading

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


class UnrelatedIntegrityErrorTests(TestCase):
    def test_an_integrity_error_that_is_not_a_duplicate_is_raised(self):
        Node.objects.create(node_id="ING-2")
        serializer = MagicMock()
        serializer.validated_data = {"node_id": "ING-2", "timestamp": timezone.now()}
        # Falla el INSERT pero no existe una lectura igual: no es un duplicado y no se debe ocultar.
        serializer.save.side_effect = IntegrityError("NOT NULL constraint failed")

        with self.assertRaises(IntegrityError):
            ingest_reading(serializer)
        self.assertFalse(SensorReading.objects.exists())
