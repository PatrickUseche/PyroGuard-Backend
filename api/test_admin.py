"""Pruebas de los filtros y búsquedas del panel de administración."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import Alert, Node, RiskAssessment, SensorReading


@override_settings(
    NODE_OFFLINE_THRESHOLD_SECONDS=300,
    # Las plantillas del admin piden estáticos; el manifiesto de WhiteNoise solo existe tras collectstatic.
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class AdminFiltersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.online = Node.objects.create(node_id="ONLINE-1", name="Bosque norte",
                                         last_communication=timezone.now() - timedelta(seconds=10))
        cls.offline = Node.objects.create(node_id="OFFLINE-1", name="Bosque sur",
                                          last_communication=timezone.now() - timedelta(hours=2))
        cls.unknown = Node.objects.create(node_id="UNKNOWN-1", name="Nuevo", is_active=False)
        for node, flame, temperature in ((cls.online, False, 20), (cls.online, True, 90), (cls.offline, False, 25)):
            reading = SensorReading.objects.create(
                node=node, temperature=temperature, humidity=40, smoke=1, flame=flame,
            )
            RiskAssessment.objects.create(
                reading=reading, risk_level="FIRE" if flame else "NORMAL", rule_reasons=[],
            )
        fire_reading = SensorReading.objects.filter(flame=True).get()
        cls.fire_alert = Alert.objects.create(node=cls.online, reading=fire_reading, level="FIRE", message="Incendio")
        cls.closed_alert = Alert.objects.create(
            node=cls.offline, reading=SensorReading.objects.filter(node=cls.offline).get(),
            level="WARNING", message="Humo", status=Alert.Status.CLOSED,
        )
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "no-se-usa")

    def setUp(self):
        self.client.force_login(self.admin)

    def rows(self, model, **params):
        response = self.client.get(reverse(f"admin:api_{model}_changelist"), params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return list(response.context["cl"].result_list)

    # --- nodos ---------------------------------------------------------------------

    def test_nodes_can_be_filtered_by_connection(self):
        self.assertEqual(self.rows("node", connection="ONLINE"), [self.online])
        self.assertEqual(self.rows("node", connection="OFFLINE"), [self.offline])
        self.assertEqual(self.rows("node", connection="UNKNOWN"), [self.unknown])

    def test_without_the_connection_filter_every_node_is_listed(self):
        self.assertEqual(len(self.rows("node")), 3)

    def test_nodes_can_be_filtered_by_active_state(self):
        self.assertEqual(self.rows("node", is_active__exact="0"), [self.unknown])

    def test_nodes_can_be_searched_by_id_and_by_name(self):
        self.assertEqual(self.rows("node", q="OFFLINE"), [self.offline])
        self.assertEqual(self.rows("node", q="bosque"), [self.offline, self.online])

    def test_the_connection_filter_follows_the_threshold(self):
        with override_settings(NODE_OFFLINE_THRESHOLD_SECONDS=86400):
            self.assertCountEqual(self.rows("node", connection="ONLINE"), [self.online, self.offline])

    # --- lecturas ------------------------------------------------------------------

    def test_readings_can_be_filtered_by_flame(self):
        rows = self.rows("sensorreading", flame__exact="1")

        self.assertEqual([r.temperature for r in rows], [90])

    def test_readings_can_be_filtered_by_node(self):
        rows = self.rows("sensorreading", node__id__exact=self.offline.pk)

        self.assertEqual([r.node for r in rows], [self.offline])

    def test_readings_can_be_filtered_by_risk_level(self):
        rows = self.rows("sensorreading", assessment__risk_level__exact="FIRE")

        self.assertEqual([r.temperature for r in rows], [90])

    def test_readings_can_be_searched_by_node(self):
        self.assertEqual(len(self.rows("sensorreading", q="ONLINE-1")), 2)
        self.assertEqual(len(self.rows("sensorreading", q="sur")), 1)

    def test_readings_can_be_filtered_by_date(self):
        year = timezone.now().year
        self.assertEqual(len(self.rows("sensorreading", timestamp__year=year)), 3)
        self.assertEqual(len(self.rows("sensorreading", timestamp__year=year - 5)), 0)

    def test_the_reading_list_does_not_query_each_node(self):
        url = reverse("admin:api_sensorreading_changelist")
        with CaptureQueriesContext(connection) as before:
            self.client.get(url)
        for _ in range(10):
            SensorReading.objects.create(node=self.online, temperature=20, humidity=40, smoke=1, flame=False)

        with CaptureQueriesContext(connection) as after:
            self.client.get(url)

        self.assertEqual(len(after), len(before))  # el nodo viene en el JOIN: no hay una consulta por fila

    # --- alertas -------------------------------------------------------------------

    def test_alerts_can_be_filtered_by_status_and_level(self):
        self.assertEqual(self.rows("alert", status__exact="ACTIVE"), [self.fire_alert])
        self.assertEqual(self.rows("alert", status__exact="CLOSED"), [self.closed_alert])
        self.assertEqual(self.rows("alert", level__exact="WARNING"), [self.closed_alert])

    def test_alerts_can_be_filtered_by_node(self):
        self.assertEqual(self.rows("alert", node__id__exact=self.online.pk), [self.fire_alert])

    def test_alerts_can_be_searched_by_node_and_message(self):
        self.assertEqual(self.rows("alert", q="ONLINE-1"), [self.fire_alert])
        self.assertEqual(self.rows("alert", q="humo"), [self.closed_alert])

    def test_alert_filters_can_be_combined(self):
        self.assertEqual(self.rows("alert", status__exact="ACTIVE", level__exact="WARNING"), [])

    def test_the_date_hierarchy_pages_load(self):
        for model in ("node", "sensorreading", "alert"):
            with self.subTest(model=model):
                self.assertEqual(
                    self.client.get(reverse(f"admin:api_{model}_changelist")).status_code, 200
                )
