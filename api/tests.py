import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import requests

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from config import settings as settings_module
from config.settings import (
    _env_bool,
    _env_non_negative_int,
    _env_positive_float,
    _env_rate,
    _env_service_url,
)

from .exceptions import api_exception_handler
from .models import Alert, Node, RiskAssessment, SensorReading
from .serializers import SensorReadingSerializer
from .services.ai_client import AIPrediction, build_payload, request_prediction
from .services.alerts import maybe_create_alert
from .services.risk_rules import evaluate_risk


_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "login": None},
)


def setUpModule():
    # Los límites reales se prueban en ThrottlingTests; el resto de la suite
    # no debe toparse con ellos porque comparten la caché de la IP de pruebas.
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


class RiskRulesTests(SimpleTestCase):
    def test_no_signals_are_normal(self):
        result = evaluate_risk(
            {"temperature": 20, "humidity": 50, "smoke": 0, "flame": False}
        )

        self.assertEqual(result["level"], "NORMAL")
        self.assertEqual(result["reasons"], [])
        self.assertIsNone(result["ai_probability"])

    def test_one_sensor_signal_is_warning(self):
        result = evaluate_risk(
            {"temperature": 42, "humidity": 50, "smoke": 0, "flame": False}
        )

        self.assertEqual(result["level"], "WARNING")

    def test_two_strong_signals_are_fire(self):
        result = evaluate_risk(
            {"temperature": 50, "humidity": 50, "smoke": 60, "flame": False}
        )

        self.assertEqual(result["level"], "FIRE")

    def test_flame_alone_does_not_declare_fire(self):
        result = evaluate_risk(
            {"temperature": 20, "humidity": 50, "smoke": 0, "flame": True}
        )

        self.assertEqual(result["level"], "WARNING")

    def test_evaluation_is_deterministic(self):
        reading_data = {
            "temperature": 42,
            "humidity": 20,
            "smoke": 40,
            "flame": False,
        }

        self.assertEqual(
            evaluate_risk(reading_data),
            evaluate_risk(reading_data),
        )

    def test_ai_none_keeps_sensor_rules_only(self):
        result = evaluate_risk(
            {"temperature": 42, "humidity": 50, "smoke": 0, "flame": False},
            ai_probability=None,
        )

        self.assertEqual(result["level"], "WARNING")
        self.assertIsNone(result["ai_probability"])

    def test_ai_probability_raises_normal_to_warning(self):
        result = evaluate_risk(
            {"temperature": 20, "humidity": 50, "smoke": 0, "flame": False},
            ai_probability=0.6,
        )

        self.assertEqual(result["level"], "WARNING")
        self.assertEqual(result["ai_probability"], 0.6)

    def test_ai_high_probability_and_sensor_signal_raise_to_fire(self):
        result = evaluate_risk(
            {"temperature": 42, "humidity": 50, "smoke": 0, "flame": False},
            ai_probability=0.9,
        )

        self.assertEqual(result["level"], "FIRE")


# Aísla la ingesta de un AI_SERVICE_URL definido en el .env local.
@override_settings(AI_SERVICE_URL="")
class ReadingsContractTests(APITestCase):
    ingest_api_key = "test-ingest-key"

    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-001")

    def test_get_returns_flat_list_with_frontend_fields(self):
        SensorReading.objects.create(
            node=self.node,
            temperature=37.5,
            humidity=22.0,
            smoke=75,
            flame=False,
        )

        response = self.client.get(reverse("receive_reading"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            set(response.data[0]),
            {
                "node_id",
                "temperature",
                "humidity",
                "smoke",
                "gas",
                "flame",
                "timestamp",
                "risk_level",
                "ai",
            },
        )
        self.assertEqual(response.data[0]["node_id"], "NODE-001")
        self.assertIsNone(response.data[0]["gas"])
        self.assertIsNone(response.data[0]["risk_level"])
        self.assertIsNone(response.data[0]["ai"])

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_without_credentials_is_rejected(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(response.data["status"], "error")
        self.assertIn("errors", response.data)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_with_valid_api_key_creates_reading(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["risk_level"], "WARNING")
        self.assertEqual(RiskAssessment.objects.count(), 1)
        self.assertNotIn(self.ingest_api_key, str(response.data))

    def test_authenticated_token_without_ingest_key_is_rejected(self):
        user = get_user_model().objects.create_user(username="trusted-client")
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(SensorReading.objects.count(), 0)

    def test_authenticated_session_without_ingest_key_is_rejected(self):
        user = get_user_model().objects.create_user(username="session-client")
        self.client.force_login(user)

        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(SensorReading.objects.count(), 0)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_with_invalid_api_key_is_rejected(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
            HTTP_X_API_KEY="invalid-key",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["status"], "error")
        self.assertNotIn("invalid-key", str(response.data))
        self.assertEqual(SensorReading.objects.count(), 0)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_with_valid_api_key_returns_uniform_validation_error(self):
        response = self.client.post(
            reverse("receive_reading"),
            {"node_id": self.node.node_id},
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("errors", response.data)
        self.assertIn("temperature", response.data["errors"])

    @override_settings(INGEST_API_KEY="", DEBUG=False)
    def test_post_is_rejected_when_ingest_key_is_not_configured(self):
        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(SensorReading.objects.count(), 0)

    @override_settings(INGEST_API_KEY="", DEBUG=True)
    def test_post_is_allowed_with_warning_when_debug_key_is_unset(self):
        with self.assertLogs("api.permissions", level="WARNING"):
            response = self.client.post(
                reverse("receive_reading"),
                self.valid_payload(),
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_rejects_missing_required_fields(self):
        response = self.client.post(
            reverse("receive_reading"),
            {"node_id": self.node.node_id},
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("temperature", response.data["errors"])

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_rejects_out_of_range_sensor_values(self):
        invalid_values = (
            ("temperature", 151),
            ("humidity", 101),
            ("smoke", -1),
            ("gas", -1),
        )
        for field, value in invalid_values:
            with self.subTest(field=field):
                payload = self.valid_payload()
                payload[field] = value
                response = self.client.post(
                    reverse("receive_reading"),
                    payload,
                    format="json",
                    HTTP_X_API_KEY=self.ingest_api_key,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data["errors"])

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_rejects_nonexistent_node(self):
        payload = self.valid_payload()
        payload["node_id"] = "NODE-MISSING"

        response = self.client.post(
            reverse("receive_reading"),
            payload,
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("NODE-MISSING", str(response.data["errors"]["node_id"]))

    @override_settings(INGEST_API_KEY=ingest_api_key, AUTO_REGISTER_NODES=True)
    def test_post_auto_registers_unknown_node(self):
        payload = self.valid_payload()
        payload["node_id"] = "NODE-AUTO"

        response = self.client.post(
            reverse("receive_reading"),
            payload,
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Node.objects.filter(node_id="NODE-AUTO").exists())

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_rejects_timestamp_more_than_five_minutes_ahead(self):
        payload = self.valid_payload()
        payload["timestamp"] = (timezone.now() + timedelta(minutes=6)).isoformat()

        response = self.client.post(
            reverse("receive_reading"),
            payload,
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("timestamp", response.data["errors"])

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_post_updates_node_last_communication_with_server_time(self):
        before_request = timezone.now()

        response = self.client.post(
            reverse("receive_reading"),
            self.valid_payload(),
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.node.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertGreaterEqual(self.node.last_communication, before_request)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    @patch(
        "api.services.ingestion.evaluate_risk",
        side_effect=RuntimeError("fallo interno de reglas"),
    )
    def test_post_keeps_reading_when_post_save_processing_fails(self, _mock_evaluate):
        with self.assertLogs("api.readings", level="ERROR"):
            response = self.client.post(
                reverse("receive_reading"),
                self.valid_payload(),
                format="json",
                HTTP_X_API_KEY=self.ingest_api_key,
            )

        self.node.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertIsNotNone(self.node.last_communication)
        self.assertIsNone(response.data["risk_level"])

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_get_filters_node_dates_order_and_limit(self):
        now = timezone.now()
        other_node = Node.objects.create(node_id="NODE-002")
        for node, minutes_ago in (
            (self.node, 3),
            (self.node, 2),
            (self.node, 1),
            (other_node, 1),
        ):
            SensorReading.objects.create(
                node=node,
                temperature=20,
                humidity=50,
                smoke=0,
                flame=False,
                timestamp=now - timedelta(minutes=minutes_ago),
            )

        response = self.client.get(
            reverse("receive_reading"),
            {
                "node_id": self.node.node_id,
                "from": (now - timedelta(minutes=4)).isoformat(),
                "to": (now - timedelta(minutes=1, seconds=30)).isoformat(),
                "limit": 1,
                "order": "asc",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["node_id"], self.node.node_id)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_get_returns_empty_list_for_no_matches_and_rejects_reversed_dates(self):
        empty_response = self.client.get(
            reverse("receive_reading"),
            {"node_id": "UNKNOWN"},
        )
        invalid_response = self.client.get(
            reverse("receive_reading"),
            {
                "from": (timezone.now() + timedelta(hours=1)).isoformat(),
                "to": timezone.now().isoformat(),
            },
        )

        self.assertEqual(empty_response.status_code, status.HTTP_200_OK)
        self.assertEqual(empty_response.data, [])
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_permission_errors_keep_uniform_shape(self):
        response = api_exception_handler(
            PermissionDenied("No autorizado."),
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("errors", response.data)

    def test_validation_errors_keep_uniform_shape(self):
        response = api_exception_handler(
            ValidationError({"field": ["Valor inválido."]}),
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("field", response.data["errors"])

    def test_unexpected_errors_return_safe_response_and_log_type(self):
        secret_detail = "private database credentials"
        with self.assertLogs("api.exceptions", level=logging.ERROR) as logs:
            response = api_exception_handler(
                RuntimeError(secret_detail),
                {},
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        self.assertEqual(
            response.data,
            {
                "status": "error",
                "errors": {"detail": "Error interno del servidor."},
            },
        )
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn(secret_detail, logs.output[0])

    def valid_payload(self):
        return {
            "node_id": self.node.node_id,
            "temperature": 37.5,
            "humidity": 22.0,
            "smoke": 75,
            "flame": False,
            "timestamp": "2026-10-06T18:30:00-05:00",
        }


class AlertServiceTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="ALERT-NODE")

    def create_assessment(self, level, reading_number):
        reading = SensorReading.objects.create(
            node=self.node,
            temperature=20,
            humidity=50,
            smoke=0,
            flame=False,
        )
        assessment = RiskAssessment.objects.create(
            reading=reading,
            risk_level=level,
            rule_reasons=[f"Lectura {reading_number}"],
        )
        return reading, assessment

    @override_settings(ALERT_ON_WARNING=True)
    def test_creates_warning_alert_when_enabled(self):
        reading, assessment = self.create_assessment("WARNING", 1)

        alert = maybe_create_alert(self.node, reading, assessment)

        self.assertEqual(alert.level, Alert.Level.WARNING)
        self.assertEqual(alert.status, Alert.Status.ACTIVE)
        self.assertIn(self.node.node_id, alert.message)
        self.assertIn("Lectura 1", alert.message)

    def test_creates_fire_alert(self):
        reading, assessment = self.create_assessment("FIRE", 1)

        alert = maybe_create_alert(self.node, reading, assessment)

        self.assertEqual(alert.level, Alert.Level.FIRE)
        self.assertEqual(Alert.objects.count(), 1)

    @override_settings(ALERT_ON_WARNING=True)
    def test_deduplicates_active_alert_and_increments_occurrences(self):
        reading, assessment = self.create_assessment("WARNING", 1)
        original_alert = maybe_create_alert(self.node, reading, assessment)
        second_reading, second_assessment = self.create_assessment("WARNING", 2)

        updated_alert = maybe_create_alert(
            self.node,
            second_reading,
            second_assessment,
        )

        self.assertEqual(updated_alert.pk, original_alert.pk)
        self.assertEqual(updated_alert.occurrences, 2)
        self.assertEqual(Alert.objects.count(), 1)
        self.assertEqual(updated_alert.reading, reading)

    @override_settings(ALERT_ON_WARNING=True)
    def test_escalation_creates_separate_fire_alert(self):
        warning_reading, warning_assessment = self.create_assessment("WARNING", 1)
        maybe_create_alert(self.node, warning_reading, warning_assessment)
        fire_reading, fire_assessment = self.create_assessment("FIRE", 2)

        fire_alert = maybe_create_alert(self.node, fire_reading, fire_assessment)

        self.assertEqual(fire_alert.level, Alert.Level.FIRE)
        self.assertEqual(Alert.objects.count(), 2)

    def test_warning_alert_is_disabled_by_default(self):
        reading, assessment = self.create_assessment("WARNING", 1)

        self.assertIsNone(maybe_create_alert(self.node, reading, assessment))
        self.assertEqual(Alert.objects.count(), 0)


class AlertEndpointTests(APITestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="API-ALERT-NODE")
        self.reading = SensorReading.objects.create(
            node=self.node,
            temperature=20,
            humidity=50,
            smoke=0,
            flame=False,
        )
        self.alert = Alert.objects.create(
            node=self.node,
            reading=self.reading,
            level=Alert.Level.FIRE,
            message="Alerta de prueba",
        )

    def test_public_list_active_list_and_detail_endpoints(self):
        list_response = self.client.get(reverse("alert_list"), {"level": "FIRE"})
        active_response = self.client.get(reverse("active_alerts"))
        detail_response = self.client.get(
            reverse("alert_detail", args=[self.alert.pk])
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(active_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(active_response.data), 1)
        self.assertEqual(detail_response.data["id"], self.alert.pk)

    def test_acknowledge_and_close_transitions(self):
        user = get_user_model().objects.create_user(username="alert-manager")
        self.client.force_authenticate(user=user)

        acknowledge_response = self.client.post(
            reverse("alert_acknowledge", args=[self.alert.pk])
        )
        close_response = self.client.post(reverse("alert_close", args=[self.alert.pk]))

        self.alert.refresh_from_db()
        self.assertEqual(acknowledge_response.status_code, status.HTTP_200_OK)
        self.assertEqual(close_response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.alert.status, Alert.Status.CLOSED)
        self.assertIsNotNone(self.alert.acknowledged_at)
        self.assertIsNotNone(self.alert.closed_at)
        self.assertEqual(Alert.objects.count(), 1)

    def test_active_can_close_directly(self):
        user = get_user_model().objects.create_user(username="alert-closer")
        self.client.force_authenticate(user=user)

        response = self.client.post(reverse("alert_close", args=[self.alert.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.Status.CLOSED)
        self.assertIsNotNone(self.alert.closed_at)

    def test_invalid_transition_returns_conflict(self):
        user = get_user_model().objects.create_user(username="alert-reviewer")
        self.client.force_authenticate(user=user)
        self.alert.status = Alert.Status.CLOSED
        self.alert.closed_at = timezone.now()
        self.alert.save(update_fields=["status", "closed_at"])

        response = self.client.post(
            reverse("alert_acknowledge", args=[self.alert.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_transition_requires_authentication(self):
        response = self.client.post(
            reverse("alert_acknowledge", args=[self.alert.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class NodeApiTests(APITestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-CRUD")

    def test_public_crud_reads_and_authenticated_create_update(self):
        self.assertEqual(self.client.get(reverse("node-list")).status_code, 200)
        detail = self.client.get(reverse("node-detail", args=[self.node.node_id]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["connection_status"], "UNKNOWN")

        denied = self.client.post(
            reverse("node-list"),
            {"node_id": "NODE-NEW", "name": "Nuevo"},
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_401_UNAUTHORIZED)

        user = get_user_model().objects.create_user(username="node-editor")
        self.client.force_authenticate(user=user)
        created = self.client.post(
            reverse("node-list"),
            {"node_id": "NODE-NEW", "name": "Nuevo"},
            format="json",
        )
        updated = self.client.patch(
            reverse("node-detail", args=[self.node.node_id]),
            {"name": "Actualizado"},
            format="json",
        )
        deleted = self.client.delete(reverse("node-detail", args=["NODE-NEW"]))

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["name"], "Actualizado")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Node.objects.filter(node_id="NODE-NEW").exists())

    def test_duplicate_node_id_and_immutable_id_return_clear_errors(self):
        user = get_user_model().objects.create_user(username="node-editor-2")
        self.client.force_authenticate(user=user)

        duplicate = self.client.post(
            reverse("node-list"),
            {"node_id": self.node.node_id},
            format="json",
        )
        changed_id = self.client.patch(
            reverse("node-detail", args=[self.node.node_id]),
            {"node_id": "NODE-OTHER"},
            format="json",
        )

        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Ya existe", str(duplicate.data["errors"]["node_id"]))
        self.assertEqual(changed_id.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "no se puede modificar",
            str(changed_id.data["errors"]["node_id"]),
        )

    @override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=60)
    def test_connection_status_unknown_online_and_offline(self):
        self.assertEqual(self.node.connection_status, "UNKNOWN")
        self.node.last_communication = timezone.now()
        self.assertEqual(self.node.connection_status, "ONLINE")
        self.node.last_communication = timezone.now() - timedelta(seconds=61)
        self.assertEqual(self.node.connection_status, "OFFLINE")

    @override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=60)
    def test_status_marks_offline_risk_as_stale(self):
        reading = SensorReading.objects.create(
            node=self.node,
            temperature=42,
            humidity=50,
            smoke=0,
            flame=False,
        )
        RiskAssessment.objects.create(
            reading=reading,
            risk_level=RiskAssessment.RiskLevel.WARNING,
            rule_reasons=["Temperatura elevada"],
        )
        self.node.last_communication = timezone.now() - timedelta(minutes=10)
        self.node.save(update_fields=["last_communication"])
        Alert.objects.create(
            node=self.node,
            reading=reading,
            level=Alert.Level.WARNING,
            message="Alerta de prueba",
        )

        response = self.client.get(
            reverse("node_status", args=[self.node.node_id])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["connection_status"], "OFFLINE")
        self.assertTrue(response.data["current_risk_stale"])
        self.assertEqual(response.data["current_risk"], "WARNING")
        self.assertEqual(response.data["active_alerts_count"], 1)
        self.assertIsNotNone(response.data["latest_reading"])

    def test_node_readings_reuse_filters_and_unknown_node_is_404(self):
        now = timezone.now()
        other_node = Node.objects.create(node_id="NODE-OTHER")
        for node, minutes in ((self.node, 2), (self.node, 1), (other_node, 1)):
            SensorReading.objects.create(
                node=node,
                temperature=20,
                humidity=50,
                smoke=0,
                flame=False,
                timestamp=now - timedelta(minutes=minutes),
            )

        response = self.client.get(
            reverse("node_readings", args=[self.node.node_id]),
            {"limit": 1, "order": "asc"},
        )
        missing = self.client.get(reverse("node_readings", args=["MISSING"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["node_id"], self.node.node_id)
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)


class DashboardAndLoginTests(APITestCase):
    def test_dashboard_summary_with_no_nodes(self):
        response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_nodes"], 0)
        self.assertEqual(response.data["nodes_online"], 0)
        self.assertEqual(response.data["nodes_offline"], 0)
        self.assertEqual(response.data["nodes_unknown"], 0)
        self.assertEqual(response.data["nodes_at_risk"], 0)
        self.assertEqual(response.data["active_alerts"], 0)
        self.assertEqual(response.data["overall_risk"], "NORMAL")
        self.assertEqual(response.data["latest_readings"], [])

    @override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=60)
    def test_dashboard_summary_counts_status_risk_and_latest_readings(self):
        now = timezone.now()
        online_node = Node.objects.create(
            node_id="SUM-ONLINE",
            last_communication=now,
        )
        offline_node = Node.objects.create(
            node_id="SUM-OFFLINE",
            last_communication=now - timedelta(minutes=5),
        )
        Node.objects.create(node_id="SUM-UNKNOWN")

        readings_by_node = {}
        for node, level in (
            (online_node, RiskAssessment.RiskLevel.FIRE),
            (offline_node, RiskAssessment.RiskLevel.WARNING),
        ):
            reading = SensorReading.objects.create(
                node=node,
                temperature=55,
                humidity=30,
                smoke=70,
                flame=True,
            )
            RiskAssessment.objects.create(
                reading=reading,
                risk_level=level,
                rule_reasons=["Prueba"],
            )
            readings_by_node[node.node_id] = reading

        Alert.objects.create(
            node=online_node,
            reading=readings_by_node[online_node.node_id],
            level=Alert.Level.FIRE,
            message="Activa",
        )
        Alert.objects.create(
            node=offline_node,
            reading=readings_by_node[offline_node.node_id],
            level=Alert.Level.WARNING,
            status=Alert.Status.ACKNOWLEDGED,
            message="Reconocida",
        )

        response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_nodes"], 3)
        self.assertEqual(response.data["nodes_online"], 1)
        self.assertEqual(response.data["nodes_offline"], 1)
        self.assertEqual(response.data["nodes_unknown"], 1)
        self.assertEqual(response.data["nodes_at_risk"], 1)
        self.assertEqual(response.data["active_alerts"], 2)
        self.assertEqual(response.data["overall_risk"], "FIRE")
        self.assertEqual(len(response.data["latest_readings"]), 2)

    def test_token_login(self):
        user = get_user_model().objects.create_user(
            username="api-login",
            password="strong-password-123",
        )

        response = self.client.post(
            reverse("api_token_auth"),
            {"username": user.username, "password": "strong-password-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)


class AIServiceSettingsTests(SimpleTestCase):
    def test_service_url_is_normalized(self):
        with patch.dict(os.environ, {"AI_SERVICE_URL": " http://127.0.0.1:8001/ "}):
            self.assertEqual(
                _env_service_url("AI_SERVICE_URL"),
                "http://127.0.0.1:8001",
            )

    def test_empty_service_url_disables_ai(self):
        with patch.dict(os.environ, {"AI_SERVICE_URL": ""}):
            self.assertEqual(_env_service_url("AI_SERVICE_URL"), "")

    def test_service_url_requires_http_scheme(self):
        with patch.dict(os.environ, {"AI_SERVICE_URL": "127.0.0.1:8001"}):
            with self.assertRaises(ImproperlyConfigured):
                _env_service_url("AI_SERVICE_URL")

    def test_timeouts_use_defaults_when_missing(self):
        for name, default in (("AI_CONNECT_TIMEOUT", 3.0), ("AI_READ_TIMEOUT", 10.0)):
            with self.subTest(name=name):
                with patch.dict(os.environ, {name: ""}):
                    self.assertEqual(_env_positive_float(name, default), default)

    def test_timeouts_are_parsed(self):
        for name, default in (("AI_CONNECT_TIMEOUT", 3.0), ("AI_READ_TIMEOUT", 10.0)):
            with self.subTest(name=name):
                with patch.dict(os.environ, {name: "4"}):
                    self.assertEqual(_env_positive_float(name, default), 4.0)

    def test_settings_define_split_timeouts(self):
        # Sin comparar valores: dependen del .env local; los defaults se prueban arriba.
        for name in ("AI_CONNECT_TIMEOUT", "AI_READ_TIMEOUT"):
            with self.subTest(name=name):
                value = getattr(settings_module, name)
                self.assertIsInstance(value, float)
                self.assertGreater(value, 0)
        self.assertFalse(hasattr(settings_module, "AI_SERVICE_TIMEOUT"))

    def test_invalid_timeout_is_rejected(self):
        for value in ("abc", "0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"AI_READ_TIMEOUT": value}):
                    with self.assertRaises(ImproperlyConfigured):
                        _env_positive_float("AI_READ_TIMEOUT", 10.0)


class RiskAssessmentAIFieldsTests(TestCase):
    def setUp(self):
        node = Node.objects.create(node_id="AI-FIELDS-NODE")
        self.reading = SensorReading.objects.create(
            node=node,
            temperature=20,
            humidity=50,
            smoke=0,
            flame=False,
        )

    def test_assessment_without_ai_defaults_to_disabled(self):
        assessment = RiskAssessment.objects.create(
            reading=self.reading,
            risk_level=RiskAssessment.RiskLevel.NORMAL,
        )

        self.assertEqual(assessment.ai_status, RiskAssessment.AIStatus.DISABLED)
        self.assertEqual(assessment.ai_risk_level, "")
        self.assertEqual(assessment.ai_probabilities, {})
        self.assertIsNone(assessment.ai_probability)

    def test_assessment_stores_ai_result(self):
        probabilities = {"NORMAL": 0.1, "WARNING": 0.2, "FIRE": 0.7}
        RiskAssessment.objects.create(
            reading=self.reading,
            risk_level=RiskAssessment.RiskLevel.FIRE,
            ai_status=RiskAssessment.AIStatus.OK,
            ai_risk_level=RiskAssessment.RiskLevel.WARNING,
            ai_probability=0.9,
            ai_probabilities=probabilities,
            ai_model_version="pyroguard-rf-1.0.0",
        )

        assessment = RiskAssessment.objects.get(reading=self.reading)
        self.assertEqual(assessment.ai_status, RiskAssessment.AIStatus.OK)
        self.assertEqual(assessment.ai_risk_level, RiskAssessment.RiskLevel.WARNING)
        self.assertEqual(assessment.ai_probabilities, probabilities)


AI_TEST_URL = "http://ia.test"
AI_TEST_CONNECT_TIMEOUT = 1.5
AI_TEST_READ_TIMEOUT = 7.5


def ai_response(status_code, body=None, raw=None):
    response = requests.Response()
    response.status_code = status_code
    content = raw if raw is not None else json.dumps(body if body is not None else {})
    response._content = content.encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def ai_success_body(**overrides):
    body = {
        "status": "ok",
        "contract_version": "1.0",
        "node_id": "AI-NODE",
        "model_version": "pyroguard-rf-1.0.0",
        "model_prediction": "FIRE",
        "risk_level": "FIRE",
        "risk_probability": 0.97,
        "probabilities": {"NORMAL": 0.03, "WARNING": 0.07, "FIRE": 0.9},
        "safety_rules": {"rule": "FIRE_CORROBORATED", "explanation": "Señales concordantes."},
    }
    body.update(overrides)
    return body


@override_settings(
    AI_SERVICE_URL=AI_TEST_URL,
    AI_CONNECT_TIMEOUT=AI_TEST_CONNECT_TIMEOUT,
    AI_READ_TIMEOUT=AI_TEST_READ_TIMEOUT,
    AI_API_KEY="",
)
class AIClientTests(SimpleTestCase):
    def setUp(self):
        self.reading = SensorReading(
            node=Node(node_id="AI-NODE"),
            temperature=48,
            humidity=10,
            smoke=320,
            gas=None,
            flame=True,
            timestamp=timezone.now(),
        )

    def predict_with(self, response=None, side_effect=None):
        with patch("api.services.ai_client.requests.post") as post:
            post.return_value = response
            post.side_effect = side_effect
            return request_prediction(self.reading), post

    @override_settings(AI_SERVICE_URL="")
    def test_disabled_without_service_url(self):
        prediction, post = self.predict_with(ai_response(200, ai_success_body()))

        self.assertEqual(prediction, AIPrediction(status=RiskAssessment.AIStatus.DISABLED))
        post.assert_not_called()

    def test_sends_contract_payload(self):
        prediction, post = self.predict_with(ai_response(200, ai_success_body()))

        self.assertTrue(prediction.ok)
        post.assert_called_once_with(
            f"{AI_TEST_URL}/predict",
            json=build_payload(self.reading),
            headers={},
            timeout=(AI_TEST_CONNECT_TIMEOUT, AI_TEST_READ_TIMEOUT),
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["node_id"], "AI-NODE")
        self.assertIsNone(payload["gas"])
        self.assertIs(payload["flame"], True)
        self.assertEqual(payload["timestamp"], self.reading.timestamp.isoformat())

    @override_settings(AI_API_KEY="clave-ia")
    def test_sends_api_key_header(self):
        _, post = self.predict_with(ai_response(200, ai_success_body()))

        self.assertEqual(post.call_args.kwargs["headers"], {"X-AI-API-Key": "clave-ia"})

    def test_parses_successful_prediction(self):
        prediction, _ = self.predict_with(ai_response(200, ai_success_body()))

        self.assertEqual(prediction.status, RiskAssessment.AIStatus.OK)
        self.assertEqual(prediction.risk_level, "FIRE")
        self.assertEqual(prediction.probability, 0.97)
        self.assertEqual(prediction.probabilities["FIRE"], 0.9)
        self.assertEqual(prediction.model_version, "pyroguard-rf-1.0.0")
        self.assertEqual(prediction.explanation, "Señales concordantes.")

    def test_accepts_minor_contract_versions(self):
        prediction, _ = self.predict_with(
            ai_response(200, ai_success_body(contract_version="1.3"))
        )

        self.assertTrue(prediction.ok)

    def test_network_errors_are_unavailable(self):
        for error in (
            requests.Timeout("lento"),
            requests.ConnectionError("rechazada"),
        ):
            with self.subTest(error=type(error).__name__):
                with self.assertLogs("api.ai", level="WARNING"):
                    prediction, _ = self.predict_with(side_effect=error)

                self.assertEqual(prediction.status, RiskAssessment.AIStatus.UNAVAILABLE)

    def test_server_errors_are_unavailable(self):
        for status_code, code in ((500, "PREDICTION_FAILED"), (503, "MODEL_UNAVAILABLE")):
            with self.subTest(status_code=status_code):
                body = {"status": "error", "code": code, "errors": {"detail": "x"}}
                with self.assertLogs("api.ai", level="WARNING") as logs:
                    prediction, _ = self.predict_with(ai_response(status_code, body))

                self.assertEqual(prediction.status, RiskAssessment.AIStatus.UNAVAILABLE)
                self.assertIn(code, logs.output[0])

    def test_rejected_credentials_are_logged_as_errors(self):
        body = {"status": "error", "code": "UNAUTHORIZED", "errors": {"detail": "x"}}
        with self.assertLogs("api.ai", level="ERROR") as logs:
            prediction, _ = self.predict_with(ai_response(401, body))

        self.assertEqual(prediction.status, RiskAssessment.AIStatus.REJECTED)
        self.assertIn("AI_API_KEY", logs.output[0])

    def test_validation_errors_are_rejected(self):
        body = {"status": "error", "code": "VALIDATION_ERROR", "errors": {"smoke": ["x"]}}
        with self.assertLogs("api.ai", level="WARNING"):
            prediction, _ = self.predict_with(ai_response(422, body))

        self.assertEqual(prediction.status, RiskAssessment.AIStatus.REJECTED)

    def test_non_json_response_is_invalid(self):
        with self.assertLogs("api.ai", level="WARNING"):
            prediction, _ = self.predict_with(ai_response(200, raw="<html>proxy</html>"))

        self.assertEqual(prediction.status, RiskAssessment.AIStatus.INVALID_RESPONSE)

    def test_non_json_error_response_is_handled(self):
        with self.assertLogs("api.ai", level="WARNING"):
            prediction, _ = self.predict_with(ai_response(502, raw="Bad Gateway"))

        self.assertEqual(prediction.status, RiskAssessment.AIStatus.UNAVAILABLE)

    def test_out_of_contract_bodies_are_invalid(self):
        invalid_bodies = {
            "lista": [ai_success_body()],
            "sin contract_version": {
                k: v for k, v in ai_success_body().items() if k != "contract_version"
            },
            "contrato 2.0": ai_success_body(contract_version="2.0"),
            "nivel desconocido": ai_success_body(risk_level="UNKNOWN"),
            "probabilidad > 1": ai_success_body(risk_probability=1.5),
            "probabilidad texto": ai_success_body(risk_probability="0.9"),
            "probabilidad booleana": ai_success_body(risk_probability=True),
            "clase desconocida": ai_success_body(probabilities={"SMOKE": 0.5}),
            "probabilities no es objeto": ai_success_body(probabilities=[0.1]),
            "sin model_version": ai_success_body(model_version=""),
        }
        for name, body in invalid_bodies.items():
            with self.subTest(name=name):
                with self.assertLogs("api.ai", level="WARNING"):
                    prediction, _ = self.predict_with(ai_response(200, body))

                self.assertEqual(
                    prediction.status,
                    RiskAssessment.AIStatus.INVALID_RESPONSE,
                )

    def test_nan_probability_is_invalid(self):
        raw = json.dumps(ai_success_body()).replace("0.97", "NaN")
        with self.assertLogs("api.ai", level="WARNING"):
            prediction, _ = self.predict_with(ai_response(200, raw=raw))

        self.assertEqual(prediction.status, RiskAssessment.AIStatus.INVALID_RESPONSE)

    def test_long_model_version_is_truncated(self):
        prediction, _ = self.predict_with(
            ai_response(200, ai_success_body(model_version="v" * 150))
        )

        self.assertEqual(len(prediction.model_version), 100)


def ai_prediction(risk_level="FIRE", probability=0.97, **overrides):
    values = {
        "status": RiskAssessment.AIStatus.OK,
        "risk_level": risk_level,
        "probability": probability,
        "probabilities": {"NORMAL": 0.03, "WARNING": 0.07, "FIRE": 0.9},
        "model_version": "pyroguard-rf-1.0.0",
        "explanation": "Señales concordantes.",
    }
    values.update(overrides)
    return AIPrediction(**values)


@override_settings(INGEST_API_KEY="test-ingest-key")
class AIIngestionTests(APITestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="AI-INGEST")

    def post_reading(self, **values):
        payload = {
            "node_id": self.node.node_id,
            "temperature": 22,
            "humidity": 60,
            "smoke": 10,
            "flame": False,
            "timestamp": timezone.now().isoformat(),
        }
        payload.update(values)
        response = self.client.post(
            reverse("receive_reading"),
            payload,
            format="json",
            HTTP_X_API_KEY="test-ingest-key",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response, RiskAssessment.objects.get(reading__node=self.node)

    @patch("api.services.ingestion.request_prediction")
    def test_stores_ai_result_and_reason(self, predict):
        predict.return_value = ai_prediction()

        response, assessment = self.post_reading(temperature=55, smoke=80, flame=True)

        self.assertEqual(response.data["risk_level"], "FIRE")
        self.assertIsNotNone(response.data["alert_id"])
        self.assertEqual(assessment.ai_status, RiskAssessment.AIStatus.OK)
        self.assertEqual(assessment.ai_risk_level, "FIRE")
        self.assertEqual(assessment.ai_probability, 0.97)
        self.assertEqual(assessment.ai_probabilities["FIRE"], 0.9)
        self.assertEqual(assessment.ai_model_version, "pyroguard-rf-1.0.0")
        self.assertIn("IA: Señales concordantes.", assessment.rule_reasons)

    @patch("api.services.ingestion.request_prediction")
    def test_ai_can_raise_risk_level(self, predict):
        predict.return_value = ai_prediction(risk_level="WARNING", probability=0.6)

        response, assessment = self.post_reading()

        self.assertEqual(response.data["risk_level"], "WARNING")
        self.assertEqual(assessment.risk_level, "WARNING")
        self.assertIn(
            "La probabilidad de IA alcanzó el nivel de advertencia.",
            assessment.rule_reasons,
        )

    @patch("api.services.ingestion.request_prediction")
    def test_ai_cannot_lower_rule_based_fire(self, predict):
        predict.return_value = ai_prediction(
            risk_level="NORMAL",
            probability=0.0,
            probabilities={"NORMAL": 1.0, "WARNING": 0.0, "FIRE": 0.0},
        )

        response, assessment = self.post_reading(temperature=55, smoke=80, flame=True)

        self.assertEqual(response.data["risk_level"], "FIRE")
        self.assertEqual(assessment.risk_level, "FIRE")
        self.assertEqual(assessment.ai_risk_level, "NORMAL")

    @patch("api.services.ingestion.request_prediction")
    def test_unavailable_ai_falls_back_to_rules(self, predict):
        predict.return_value = AIPrediction(status=RiskAssessment.AIStatus.UNAVAILABLE)

        response, assessment = self.post_reading(temperature=45)

        self.assertEqual(response.data["risk_level"], "WARNING")
        self.assertEqual(assessment.ai_status, RiskAssessment.AIStatus.UNAVAILABLE)
        self.assertIsNone(assessment.ai_probability)
        self.assertEqual(assessment.ai_risk_level, "")
        self.assertFalse(any(reason.startswith("IA:") for reason in assessment.rule_reasons))

    @override_settings(AI_SERVICE_URL="")
    def test_disabled_ai_is_recorded(self):
        _, assessment = self.post_reading()

        self.assertEqual(assessment.risk_level, "NORMAL")
        self.assertEqual(assessment.ai_status, RiskAssessment.AIStatus.DISABLED)

    @patch(
        "api.services.ingestion.request_prediction",
        side_effect=RuntimeError("fallo del cliente"),
    )
    def test_unexpected_client_error_keeps_reading_and_uses_rules(self, _predict):
        with self.assertLogs("api.readings", level="ERROR"):
            response, assessment = self.post_reading(temperature=45)

        self.assertEqual(response.data["risk_level"], "WARNING")
        self.assertEqual(assessment.ai_status, RiskAssessment.AIStatus.UNAVAILABLE)
        self.assertEqual(SensorReading.objects.count(), 1)


@override_settings(INGEST_API_KEY="test-ingest-key")
class AIIngestionTransactionTests(TransactionTestCase):
    def test_ai_is_called_after_reading_is_committed(self):
        node = Node.objects.create(node_id="AI-TX")
        observed = {}

        def fake_prediction(reading):
            observed["in_atomic_block"] = connection.in_atomic_block
            observed["reading_committed"] = SensorReading.objects.filter(
                pk=reading.pk
            ).exists()
            return AIPrediction(status=RiskAssessment.AIStatus.UNAVAILABLE)

        with patch(
            "api.services.ingestion.request_prediction",
            side_effect=fake_prediction,
        ):
            response = self.client.post(
                reverse("receive_reading"),
                {
                    "node_id": node.node_id,
                    "temperature": 22,
                    "humidity": 60,
                    "smoke": 10,
                    "flame": False,
                    "timestamp": timezone.now().isoformat(),
                },
                content_type="application/json",
                HTTP_X_API_KEY="test-ingest-key",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            observed,
            {"in_atomic_block": False, "reading_committed": True},
        )


@override_settings(INGEST_API_KEY="test-ingest-key")
class AIReadingRepresentationTests(APITestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="AI-API")

    @patch("api.services.ingestion.request_prediction")
    def post_reading(self, prediction, predict):
        predict.return_value = prediction
        return self.client.post(
            reverse("receive_reading"),
            {
                "node_id": self.node.node_id,
                "temperature": 22,
                "humidity": 60,
                "smoke": 10,
                "flame": False,
                "timestamp": timezone.now().isoformat(),
            },
            format="json",
            HTTP_X_API_KEY="test-ingest-key",
        )

    def test_post_response_includes_ai_result(self):
        response = self.post_reading(ai_prediction(risk_level="WARNING", probability=0.6))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["risk_level"], "WARNING")
        self.assertEqual(
            response.data["reading"]["ai"],
            {
                "status": "OK",
                "risk_level": "WARNING",
                "probability": 0.6,
                "probabilities": {"NORMAL": 0.03, "WARNING": 0.07, "FIRE": 0.9},
                "model_version": "pyroguard-rf-1.0.0",
            },
        )

    def test_unavailable_ai_is_reported_with_empty_values(self):
        response = self.post_reading(
            AIPrediction(status=RiskAssessment.AIStatus.UNAVAILABLE)
        )

        self.assertEqual(
            response.data["reading"]["ai"],
            {
                "status": "UNAVAILABLE",
                "risk_level": None,
                "probability": None,
                "probabilities": {},
                "model_version": None,
            },
        )

    def test_reading_lists_include_ai_result(self):
        self.post_reading(ai_prediction(risk_level="WARNING", probability=0.6))

        for url in (
            reverse("receive_reading"),
            reverse("node_readings", args=[self.node.node_id]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.data[0]["ai"]["status"], "OK")
                self.assertEqual(response.data[0]["ai"]["probability"], 0.6)

        summary = self.client.get(reverse("dashboard_summary"))
        self.assertEqual(summary.data["latest_readings"][0]["ai"]["status"], "OK")

    def test_reading_list_does_not_query_per_reading(self):
        for _ in range(5):
            self.post_reading(ai_prediction(risk_level="WARNING", probability=0.6))

        # Una consulta para la página y otra para X-Total-Count; no crece con las lecturas.
        with self.assertNumQueries(2):
            response = self.client.get(reverse("receive_reading"))

        self.assertEqual(len(response.data), 5)


@override_settings(
    INGEST_API_KEY="test-ingest-key",
    AI_SERVICE_URL=AI_TEST_URL,
    AI_CONNECT_TIMEOUT=AI_TEST_CONNECT_TIMEOUT,
    AI_READ_TIMEOUT=AI_TEST_READ_TIMEOUT,
    AI_API_KEY="clave-ia",
)
class AIIngestionResilienceTests(APITestCase):
    """Recorre endpoint, ingesta y cliente real simulando solo la red."""

    normal_values = {"temperature": 22, "humidity": 60, "smoke": 10, "flame": False}
    fire_values = {"temperature": 55, "humidity": 20, "smoke": 80, "flame": True}

    failures = {
        "timeout": (requests.Timeout("lento"), RiskAssessment.AIStatus.UNAVAILABLE),
        "conexión rechazada": (
            requests.ConnectionError("rechazada"),
            RiskAssessment.AIStatus.UNAVAILABLE,
        ),
        "HTTP 500": (
            ai_response(500, {"status": "error", "code": "PREDICTION_FAILED"}),
            RiskAssessment.AIStatus.UNAVAILABLE,
        ),
        "HTTP 503": (
            ai_response(503, {"status": "error", "code": "MODEL_UNAVAILABLE"}),
            RiskAssessment.AIStatus.UNAVAILABLE,
        ),
        "HTTP 401": (
            ai_response(401, {"status": "error", "code": "UNAUTHORIZED"}),
            RiskAssessment.AIStatus.REJECTED,
        ),
        "HTTP 422": (
            ai_response(422, {"status": "error", "code": "VALIDATION_ERROR"}),
            RiskAssessment.AIStatus.REJECTED,
        ),
        "HTML de un proxy": (
            ai_response(200, raw="<html>proxy</html>"),
            RiskAssessment.AIStatus.INVALID_RESPONSE,
        ),
        "contrato incompatible": (
            ai_response(200, ai_success_body(contract_version="2.0")),
            RiskAssessment.AIStatus.INVALID_RESPONSE,
        ),
    }

    def setUp(self):
        self.node = Node.objects.create(node_id="AI-RESILIENCE")

    def post_reading(self, ai_outcome, **values):
        payload = {
            "node_id": self.node.node_id,
            "timestamp": timezone.now().isoformat(),
            **values,
        }
        with patch("api.services.ai_client.requests.post") as post:
            if isinstance(ai_outcome, Exception):
                post.side_effect = ai_outcome
            else:
                post.return_value = ai_outcome
            with self.assertNoLogs("api.readings", level="ERROR"):
                response = self.client.post(
                    reverse("receive_reading"),
                    payload,
                    format="json",
                    HTTP_X_API_KEY="test-ingest-key",
                )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response, post

    def test_ai_failures_keep_reading_and_use_rules(self):
        for name, (outcome, expected_status) in self.failures.items():
            with self.subTest(name=name):
                readings_before = SensorReading.objects.count()
                with self.assertLogs("api.ai", level="WARNING"):
                    response, _ = self.post_reading(outcome, **self.normal_values)

                self.assertEqual(SensorReading.objects.count(), readings_before + 1)
                self.assertEqual(response.data["risk_level"], "NORMAL")
                self.assertIsNone(response.data["alert_id"])
                self.assertEqual(response.data["reading"]["ai"]["status"], expected_status)
                self.assertIsNone(response.data["reading"]["ai"]["probability"])

        self.assertFalse(Alert.objects.exists())

    def test_ai_failure_never_suppresses_fire_alert(self):
        for name, (outcome, expected_status) in self.failures.items():
            with self.subTest(name=name):
                Alert.objects.all().delete()
                with self.assertLogs("api.ai", level="WARNING"):
                    response, _ = self.post_reading(outcome, **self.fire_values)

                self.assertEqual(response.data["risk_level"], "FIRE")
                self.assertEqual(response.data["reading"]["ai"]["status"], expected_status)
                alert = Alert.objects.get(pk=response.data["alert_id"])
                self.assertEqual(alert.level, Alert.Level.FIRE)

    def test_ai_probability_raises_to_fire_and_creates_alert(self):
        warning_values = {**self.normal_values, "temperature": 45}

        response, post = self.post_reading(
            ai_response(200, ai_success_body(risk_probability=0.9)),
            **warning_values,
        )

        self.assertEqual(response.data["risk_level"], "FIRE")
        self.assertEqual(response.data["reading"]["ai"]["status"], "OK")
        self.assertEqual(Alert.objects.get().level, Alert.Level.FIRE)
        self.assertEqual(post.call_args.kwargs["headers"], {"X-AI-API-Key": "clave-ia"})
        self.assertEqual(
            post.call_args.kwargs["timeout"],
            (AI_TEST_CONNECT_TIMEOUT, AI_TEST_READ_TIMEOUT),
        )

    def test_saved_reading_is_sent_according_to_contract(self):
        _, post = self.post_reading(
            ai_response(200, ai_success_body(risk_level="NORMAL", risk_probability=0.0)),
            **{**self.normal_values, "flame": 1},
        )

        sent = post.call_args.kwargs["json"]
        reading = SensorReading.objects.get()
        self.assertEqual(post.call_args.args[0], f"{AI_TEST_URL}/predict")
        self.assertEqual(
            sent,
            {
                "node_id": "AI-RESILIENCE",
                "temperature": 22.0,
                "humidity": 60.0,
                "smoke": 10.0,
                "gas": None,
                "flame": True,
                "timestamp": reading.timestamp.isoformat(),
            },
        )


CONTRACT_EXAMPLES_DIR = Path(__file__).resolve().parent / "contract_examples"


def contract_example(name):
    return json.loads((CONTRACT_EXAMPLES_DIR / name).read_text(encoding="utf-8"))


@override_settings(
    AI_SERVICE_URL=AI_TEST_URL,
    AI_CONNECT_TIMEOUT=AI_TEST_CONNECT_TIMEOUT,
    AI_READ_TIMEOUT=AI_TEST_READ_TIMEOUT,
    AI_API_KEY="",
)
class AIContractExamplesTests(TestCase):
    """Usa los ejemplos compartidos con PyroGuard-IA (docs/contract/examples)."""

    def setUp(self):
        Node.objects.create(node_id="NODE-001")

    def save_reading(self, example):
        serializer = SensorReadingSerializer(data=example)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_request_examples_are_valid_readings_and_round_trip(self):
        for path in sorted(CONTRACT_EXAMPLES_DIR.glob("request_*.json")):
            with self.subTest(example=path.name):
                example = contract_example(path.name)
                payload = build_payload(self.save_reading(example))

                sent_timestamp = datetime.fromisoformat(payload.pop("timestamp"))
                expected_timestamp = datetime.fromisoformat(example.pop("timestamp"))
                self.assertEqual(sent_timestamp, expected_timestamp)
                self.assertEqual(payload, example)

    def test_response_example_is_parsed(self):
        reading = self.save_reading(contract_example("request_fire.json"))
        example = contract_example("response_ok.json")

        with patch("api.services.ai_client.requests.post") as post:
            post.return_value = ai_response(200, example)
            prediction = request_prediction(reading)

        self.assertEqual(prediction.status, RiskAssessment.AIStatus.OK)
        self.assertEqual(prediction.risk_level, example["risk_level"])
        self.assertEqual(prediction.probability, example["risk_probability"])
        self.assertEqual(prediction.probabilities, example["probabilities"])
        self.assertEqual(prediction.model_version, example["model_version"])
        self.assertEqual(prediction.explanation, example["safety_rules"]["explanation"])

    def test_error_examples_map_to_ai_status(self):
        reading = self.save_reading(contract_example("request_fire.json"))
        cases = {
            "error_validation.json": (422, RiskAssessment.AIStatus.REJECTED),
            "error_unauthorized.json": (401, RiskAssessment.AIStatus.REJECTED),
            "error_model_unavailable.json": (503, RiskAssessment.AIStatus.UNAVAILABLE),
        }
        for name, (status_code, expected_status) in cases.items():
            with self.subTest(example=name):
                with patch("api.services.ai_client.requests.post") as post:
                    post.return_value = ai_response(status_code, contract_example(name))
                    with self.assertLogs("api.ai", level="WARNING") as logs:
                        prediction = request_prediction(reading)

                self.assertEqual(prediction.status, expected_status)
                if status_code != 401:
                    self.assertIn(contract_example(name)["code"], logs.output[0])


class ThrottlingTests(APITestCase):
    ingest_api_key = "test-ingest-key"

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.node = Node.objects.create(node_id="NODE-001")

    def limit(self, read="1000/min", ingest="1000/min", login="1000/min"):
        return patch.object(
            SimpleRateThrottle,
            "THROTTLE_RATES",
            {"read": read, "ingest": ingest, "login": login},
        )

    def post_reading(self):
        return self.client.post(
            reverse("receive_reading"),
            {},
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

    def test_read_requests_are_limited_per_ip(self):
        with self.limit(read="3/min"):
            statuses = [
                self.client.get(reverse("dashboard_summary")).status_code
                for _ in range(4)
            ]

        self.assertEqual(statuses, [200, 200, 200, 429])

    def test_throttled_response_tells_when_to_retry(self):
        with self.limit(read="1/min"):
            self.client.get(reverse("dashboard_summary"))
            response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertGreater(int(response["Retry-After"]), 0)

    def test_read_limit_is_shared_by_all_get_endpoints(self):
        with self.limit(read="2/min"):
            first = self.client.get(reverse("dashboard_summary"))
            second = self.client.get(reverse("receive_reading"))
            third = self.client.get(reverse("alert_list"))

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_ingest_requests_are_limited_per_ip(self):
        with self.limit(ingest="2/min"):
            statuses = [self.post_reading().status_code for _ in range(3)]

        self.assertEqual(statuses, [400, 400, 429])

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_ingest_limit_does_not_consume_the_read_limit(self):
        with self.limit(read="1/min", ingest="5/min"):
            for _ in range(3):
                self.post_reading()
            response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(INGEST_API_KEY=ingest_api_key)
    def test_exhausted_ingest_limit_does_not_block_reads(self):
        with self.limit(read="5/min", ingest="1/min"):
            self.post_reading()
            blocked = self.post_reading()
            response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_requests_without_valid_key_are_rejected_before_counting(self):
        with override_settings(INGEST_API_KEY=self.ingest_api_key):
            with self.limit(ingest="1/min"):
                responses = [
                    self.client.post(reverse("receive_reading"), {}, format="json")
                    for _ in range(3)
                ]

        self.assertEqual(
            [response.status_code for response in responses],
            [status.HTTP_401_UNAUTHORIZED] * 3,
        )

    def login(self, password="mala"):
        return self.client.post(
            reverse("api_token_auth"),
            {"username": "operador", "password": password},
            format="json",
        )

    def test_login_attempts_are_limited_per_ip(self):
        get_user_model().objects.create_user("operador", password="buena")

        with self.limit(login="3/min"):
            statuses = [self.login().status_code for _ in range(4)]

        self.assertEqual(statuses, [400, 400, 400, 429])

    def test_correct_password_is_also_blocked_once_the_limit_is_reached(self):
        get_user_model().objects.create_user("operador", password="buena")

        with self.limit(login="2/min"):
            self.login()
            self.login()
            response = self.login(password="buena")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertGreater(int(response["Retry-After"]), 0)

    def test_login_limit_does_not_consume_the_read_limit(self):
        with self.limit(read="1/min", login="5/min"):
            for _ in range(3):
                self.login()
            response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_exhausted_login_limit_does_not_block_reads(self):
        with self.limit(read="5/min", login="1/min"):
            self.login()
            blocked = self.login()
            response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_still_returns_a_token_within_the_limit(self):
        get_user_model().objects.create_user("operador", password="buena")

        with self.limit(login="3/min"):
            response = self.login(password="buena")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

    def test_settings_define_every_scope(self):
        rates = settings_module.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]

        self.assertEqual(set(rates), {"read", "ingest", "login"})
        self.assertIn(
            "api.throttles.ReadThrottle",
            settings_module.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"],
        )


class ThrottleSettingsTests(SimpleTestCase):
    def test_rate_uses_default_when_missing(self):
        with patch.dict(os.environ, {"THROTTLE_READ_RATE": ""}):
            self.assertEqual(_env_rate("THROTTLE_READ_RATE", "120/min"), "120/min")

    def test_rate_is_parsed(self):
        for value in ("5/sec", " 120/min ", "10/hour", "1000/day"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"THROTTLE_READ_RATE": value}):
                    self.assertEqual(
                        _env_rate("THROTTLE_READ_RATE", "120/min"), value.strip()
                    )

    def test_invalid_rate_is_rejected(self):
        for value in ("abc", "120", "0/min", "-1/min", "10/year", "1.5/min"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"THROTTLE_READ_RATE": value}):
                    with self.assertRaises(ImproperlyConfigured):
                        _env_rate("THROTTLE_READ_RATE", "120/min")

    def test_num_proxies_is_optional(self):
        with patch.dict(os.environ, {"NUM_PROXIES": ""}):
            self.assertIsNone(_env_non_negative_int("NUM_PROXIES"))

    def test_num_proxies_accepts_zero_and_positive_values(self):
        for value, expected in (("0", 0), ("1", 1), (" 2 ", 2)):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"NUM_PROXIES": value}):
                    self.assertEqual(_env_non_negative_int("NUM_PROXIES"), expected)

    def test_invalid_num_proxies_is_rejected(self):
        for value in ("abc", "-1", "1.5"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"NUM_PROXIES": value}):
                    with self.assertRaises(ImproperlyConfigured):
                        _env_non_negative_int("NUM_PROXIES")


class ReadAccessTests(APITestCase):
    ingest_api_key = "test-ingest-key"

    def setUp(self):
        self.node = Node.objects.create(node_id="ACCESS-NODE")
        self.reading = SensorReading.objects.create(
            node=self.node,
            temperature=20,
            humidity=50,
            smoke=0,
            flame=False,
        )
        self.alert = Alert.objects.create(
            node=self.node,
            reading=self.reading,
            level=Alert.Level.FIRE,
            message="Alerta de prueba",
        )
        self.user = get_user_model().objects.create_user("operador", password="x")

    def read_urls(self):
        return {
            "receive_reading": reverse("receive_reading"),
            "dashboard_summary": reverse("dashboard_summary"),
            "node_list": reverse("node-list"),
            "node_detail": reverse("node-detail", args=[self.node.node_id]),
            "node_status": reverse("node_status", args=[self.node.node_id]),
            "node_readings": reverse("node_readings", args=[self.node.node_id]),
            "alert_list": reverse("alert_list"),
            "active_alerts": reverse("active_alerts"),
            "alert_detail": reverse("alert_detail", args=[self.alert.pk]),
        }

    def test_reads_are_public_by_default(self):
        self.assertTrue(settings_module.PUBLIC_READ_ACCESS)
        for name, url in self.read_urls().items():
            with self.subTest(endpoint=name):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_closed_reads_require_authentication(self):
        for name, url in self.read_urls().items():
            with self.subTest(endpoint=name):
                response = self.client.get(url)

                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_closed_reads_work_with_a_token(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        for name, url in self.read_urls().items():
            with self.subTest(endpoint=name):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_closed_reads_do_not_block_the_login(self):
        response = self.client.post(
            reverse("api_token_auth"),
            {"username": "operador", "password": "x"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

    @override_settings(PUBLIC_READ_ACCESS=False, INGEST_API_KEY=ingest_api_key)
    def test_closed_reads_do_not_block_ingestion_with_the_api_key(self):
        response = self.client.post(
            reverse("receive_reading"),
            {
                "node_id": self.node.node_id,
                "temperature": 24.5,
                "humidity": 48,
                "smoke": 18,
                "flame": False,
                "timestamp": timezone.now().isoformat(),
            },
            format="json",
            HTTP_X_API_KEY=self.ingest_api_key,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_writes_still_require_authentication_when_reads_are_public(self):
        response = self.client.post(
            reverse("node-list"), {"node_id": "NEW-NODE"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PaginationTests(APITestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="PAGE-NODE")
        self.other_node = Node.objects.create(node_id="OTHER-NODE")
        base = timezone.now() - timedelta(hours=1)
        for index in range(5):
            SensorReading.objects.create(
                node=self.node,
                temperature=20 + index,
                humidity=50,
                smoke=0,
                flame=False,
                timestamp=base + timedelta(minutes=index),
            )
        SensorReading.objects.create(
            node=self.other_node,
            temperature=30,
            humidity=50,
            smoke=0,
            flame=False,
        )

    def temperatures(self, response):
        return [item["temperature"] for item in response.data]

    def test_offset_and_limit_select_a_page(self):
        response = self.client.get(
            reverse("receive_reading"),
            {"node_id": "PAGE-NODE", "order": "asc", "limit": 2, "offset": 2},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.temperatures(response), [22, 23])

    def test_total_count_ignores_the_page_but_respects_filters(self):
        response = self.client.get(
            reverse("receive_reading"), {"node_id": "PAGE-NODE", "limit": 2}
        )

        self.assertEqual(len(response.data), 2)
        self.assertEqual(response["X-Total-Count"], "5")

    def test_total_count_counts_every_node_without_filter(self):
        response = self.client.get(reverse("receive_reading"))

        self.assertEqual(response["X-Total-Count"], "6")

    def test_node_readings_endpoint_is_paginated_too(self):
        response = self.client.get(
            reverse("node_readings", args=["PAGE-NODE"]),
            {"order": "asc", "limit": 3, "offset": 4},
        )

        self.assertEqual(self.temperatures(response), [24])
        self.assertEqual(response["X-Total-Count"], "5")

    def test_offset_past_the_end_returns_an_empty_list_with_total(self):
        response = self.client.get(reverse("receive_reading"), {"offset": 100})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        self.assertEqual(response["X-Total-Count"], "6")

    def test_default_limit_is_twenty_for_readings(self):
        node = Node.objects.create(node_id="MANY-NODE")
        SensorReading.objects.bulk_create(
            SensorReading(
                node=node, temperature=20, humidity=50, smoke=0, flame=False
            )
            for _ in range(25)
        )

        response = self.client.get(reverse("receive_reading"), {"node_id": "MANY-NODE"})

        self.assertEqual(len(response.data), 20)
        self.assertEqual(response["X-Total-Count"], "25")

    def test_invalid_limit_and_offset_are_rejected(self):
        for name, value in (
            ("limit", "0"),
            ("limit", "501"),
            ("limit", "abc"),
            ("offset", "-1"),
            ("offset", "abc"),
        ):
            with self.subTest(name=name, value=value):
                response = self.client.get(reverse("receive_reading"), {name: value})

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(name, str(response.data["errors"]))

    def test_impossible_date_is_reported_as_a_date_error(self):
        response = self.client.get(
            reverse("receive_reading"), {"from": "2026-13-45T00:00:00Z"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("from", str(response.data["errors"]))
        self.assertNotIn("limit", str(response.data["errors"]))

    def test_alerts_are_paginated_with_a_default_of_one_hundred(self):
        reading = SensorReading.objects.filter(node=self.node).first()
        Alert.objects.bulk_create(
            Alert(
                node=self.node,
                reading=reading,
                level=Alert.Level.WARNING,
                message=f"Alerta {index}",
            )
            for index in range(105)
        )

        default_page = self.client.get(reverse("alert_list"))
        custom_page = self.client.get(reverse("alert_list"), {"limit": 10, "offset": 100})

        self.assertEqual(len(default_page.data), 100)
        self.assertEqual(default_page["X-Total-Count"], "105")
        self.assertEqual(len(custom_page.data), 5)

    def test_alert_total_respects_filters(self):
        reading = SensorReading.objects.filter(node=self.node).first()
        Alert.objects.create(
            node=self.node, reading=reading, level=Alert.Level.FIRE, message="Fuego"
        )
        Alert.objects.create(
            node=self.node, reading=reading, level=Alert.Level.WARNING, message="Aviso"
        )

        response = self.client.get(reverse("alert_list"), {"level": "FIRE"})

        self.assertEqual(response["X-Total-Count"], "1")

    def test_invalid_alert_limit_is_rejected(self):
        response = self.client.get(reverse("alert_list"), {"limit": "501"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cors_exposes_the_pagination_header_to_the_frontend(self):
        response = self.client.get(
            reverse("receive_reading"), HTTP_ORIGIN="http://localhost:4200"
        )

        exposed = response["Access-Control-Expose-Headers"]
        self.assertIn("X-Total-Count", exposed)
        self.assertIn("Retry-After", exposed)


class BooleanSettingsTests(SimpleTestCase):
    def test_missing_variable_uses_the_default(self):
        with patch.dict(os.environ, clear=False):
            os.environ.pop("PRUEBA_BOOL", None)
            self.assertIs(_env_bool("PRUEBA_BOOL", True), True)
            self.assertIs(_env_bool("PRUEBA_BOOL", False), False)

    def test_empty_or_blank_variable_uses_the_default(self):
        for value in ("", "   "):
            for default in (True, False):
                with self.subTest(value=value, default=default):
                    with patch.dict(os.environ, {"PRUEBA_BOOL": value}):
                        self.assertIs(_env_bool("PRUEBA_BOOL", default), default)

    def test_true_values_are_accepted(self):
        for value in ("true", "True", "TRUE", "1", "yes", "on", " true "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"PRUEBA_BOOL": value}):
                    self.assertIs(_env_bool("PRUEBA_BOOL", False), True)

    def test_false_values_are_accepted(self):
        for value in ("false", "False", "FALSE", "0", "no", "off", " false "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"PRUEBA_BOOL": value}):
                    self.assertIs(_env_bool("PRUEBA_BOOL", True), False)

    def test_invalid_value_is_rejected_naming_the_variable(self):
        for value in ("falso", "production", "2", "'False'"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"PRUEBA_BOOL": value}):
                    with self.assertRaisesMessage(ValueError, "PRUEBA_BOOL"):
                        _env_bool("PRUEBA_BOOL", False)


class ProcfileTests(SimpleTestCase):
    def test_procfile_migrates_and_collects_static_before_starting_gunicorn(self):
        procfile = (Path(settings_module.BASE_DIR) / "Procfile").read_text(
            encoding="utf-8"
        )

        migrate = procfile.index("manage.py migrate --noinput")
        collectstatic = procfile.index("manage.py collectstatic --noinput")
        gunicorn = procfile.index("gunicorn config.wsgi:application")

        self.assertLess(migrate, collectstatic)
        self.assertLess(collectstatic, gunicorn)
        self.assertIn("--bind 0.0.0.0:$PORT", procfile)
