import logging
import os
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APITestCase

from config.settings import _env_positive_float, _env_service_url

from .exceptions import api_exception_handler
from .models import Alert, Node, RiskAssessment, SensorReading
from .services.alerts import maybe_create_alert
from .services.risk_rules import evaluate_risk


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
            },
        )
        self.assertEqual(response.data[0]["node_id"], "NODE-001")
        self.assertIsNone(response.data[0]["gas"])
        self.assertIsNone(response.data[0]["risk_level"])

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

    def test_timeout_uses_default_when_missing(self):
        with patch.dict(os.environ, {"AI_SERVICE_TIMEOUT": ""}):
            self.assertEqual(_env_positive_float("AI_SERVICE_TIMEOUT", 2.5), 2.5)

    def test_timeout_is_parsed(self):
        with patch.dict(os.environ, {"AI_SERVICE_TIMEOUT": "4"}):
            self.assertEqual(_env_positive_float("AI_SERVICE_TIMEOUT", 2.5), 4.0)

    def test_invalid_timeout_is_rejected(self):
        for value in ("abc", "0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"AI_SERVICE_TIMEOUT": value}):
                    with self.assertRaises(ImproperlyConfigured):
                        _env_positive_float("AI_SERVICE_TIMEOUT", 2.5)


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
