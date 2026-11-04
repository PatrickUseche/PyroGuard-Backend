"""Pruebas de la búsqueda de nodos por prefijo."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Node
from .services.node_search import node_search_index

_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "google_login": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


class NodeSearchTests(APITestCase):
    def setUp(self):
        node_search_index.clear()
        self.addCleanup(node_search_index.clear)
        for node_id in ("SIM-001", "SIM-002", "SIM-010", "bosque-norte", "Bosque-Sur"):
            Node.objects.create(node_id=node_id)

    def search(self, **params):
        return self.client.get(reverse("node_search"), params)

    def test_finds_the_nodes_that_start_with_the_prefix(self):
        response = self.search(prefix="SIM-0")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["prefix"], "SIM-0")
        self.assertEqual(response.data["results"], ["SIM-001", "SIM-002", "SIM-010"])

    def test_a_longer_prefix_narrows_the_results(self):
        self.assertEqual(self.search(prefix="SIM-00").data["results"], ["SIM-001", "SIM-002"])
        self.assertEqual(self.search(prefix="SIM-001").data["results"], ["SIM-001"])

    def test_results_are_in_alphabetical_order(self):
        results = self.search(prefix="").data["results"]

        self.assertEqual(results, sorted(results, key=str.casefold))

    def test_search_ignores_case_but_keeps_the_stored_spelling(self):
        self.assertEqual(
            self.search(prefix="BOSQUE").data["results"],
            ["bosque-norte", "Bosque-Sur"],
        )
        self.assertEqual(self.search(prefix="sim-010").data["results"], ["SIM-010"])

    def test_without_a_prefix_it_lists_the_first_nodes(self):
        response = self.search()

        self.assertEqual(response.data["prefix"], "")
        self.assertEqual(len(response.data["results"]), 5)

    def test_unknown_prefix_returns_an_empty_list(self):
        response = self.search(prefix="zzz")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])

    def test_the_prefix_is_trimmed(self):
        self.assertEqual(self.search(prefix="  SIM-010 ").data["results"], ["SIM-010"])

    def test_limit_cuts_the_results(self):
        self.assertEqual(self.search(prefix="SIM", limit=2).data["results"], ["SIM-001", "SIM-002"])

    def test_invalid_limit_is_rejected(self):
        for limit in ("0", "101", "-1", "abc", "2.5"):
            with self.subTest(limit=limit):
                self.assertEqual(
                    self.search(prefix="SIM", limit=limit).status_code,
                    status.HTTP_400_BAD_REQUEST,
                )

    def test_the_index_is_built_once_and_then_serves_without_queries(self):
        self.search(prefix="SIM")

        with self.assertNumQueries(0):
            self.search(prefix="SIM")

    def test_a_new_node_appears_without_rebuilding_the_index(self):
        self.search(prefix="SIM")

        Node.objects.create(node_id="SIM-003")

        self.assertEqual(
            self.search(prefix="SIM-00").data["results"],
            ["SIM-001", "SIM-002", "SIM-003"],
        )

    def test_a_deleted_node_disappears_from_the_results(self):
        self.search(prefix="SIM")

        Node.objects.get(node_id="SIM-002").delete()

        self.assertEqual(self.search(prefix="SIM-00").data["results"], ["SIM-001"])

    def test_nodes_created_through_the_api_are_searchable(self):
        user = get_user_model().objects.create_user("operador", password="clave-segura-1")
        token = Token.objects.create(user=user)
        self.search(prefix="x")  # carga el índice

        response = self.client.post(
            reverse("node-list"),
            {"node_id": "XENON-1", "name": "Xenón"},
            format="json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.search(prefix="xen").data["results"], ["XENON-1"])

    def test_updating_a_node_keeps_it_in_the_index(self):
        self.search(prefix="SIM")

        node = Node.objects.get(node_id="SIM-001")
        node.name = "Nuevo nombre"
        node.save()

        self.assertEqual(self.search(prefix="SIM-001").data["results"], ["SIM-001"])

    def test_the_search_route_does_not_clash_with_node_detail(self):
        detail = self.client.get(reverse("node-detail", args=["SIM-001"]))

        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["node_id"], "SIM-001")

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_requires_authentication_when_reads_are_private(self):
        self.assertEqual(self.search(prefix="SIM").status_code, status.HTTP_401_UNAUTHORIZED)
