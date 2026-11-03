"""Pruebas del grafo de nodos vecinos: modelo, grafo en memoria y API de vínculos."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Node, NodeLink
from .services.node_graph import node_graph


_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "login": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


def make_nodes(*node_ids):
    return {node_id: Node.objects.create(node_id=node_id) for node_id in node_ids}


class NodeLinkModelTests(TestCase):
    def setUp(self):
        self.nodes = make_nodes("A", "B", "C")

    def test_the_ends_are_stored_in_pk_order(self):
        link = NodeLink.objects.create(node_a=self.nodes["B"], node_b=self.nodes["A"])

        self.assertEqual(link.node_a, self.nodes["A"])
        self.assertEqual(link.node_b, self.nodes["B"])

    def test_the_same_pair_cannot_be_stored_twice_in_either_order(self):
        NodeLink.objects.create(node_a=self.nodes["A"], node_b=self.nodes["B"])

        with self.assertRaises(IntegrityError), transaction.atomic():
            NodeLink.objects.create(node_a=self.nodes["B"], node_b=self.nodes["A"])

    def test_a_node_cannot_be_linked_to_itself(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            NodeLink.objects.create(node_a=self.nodes["A"], node_b=self.nodes["A"])

    def test_deleting_a_node_deletes_its_links(self):
        NodeLink.objects.create(node_a=self.nodes["A"], node_b=self.nodes["B"])
        NodeLink.objects.create(node_a=self.nodes["B"], node_b=self.nodes["C"])

        self.nodes["B"].delete()

        self.assertEqual(NodeLink.objects.count(), 0)

    def test_string_representation(self):
        link = NodeLink.objects.create(node_a=self.nodes["B"], node_b=self.nodes["A"])

        self.assertEqual(str(link), "A <-> B")


class NodeGraphTests(TestCase):
    def setUp(self):
        node_graph.clear()
        self.addCleanup(node_graph.clear)
        self.nodes = make_nodes("A", "B", "C", "D", "SOLO")
        for first, second in (("A", "B"), ("B", "C"), ("C", "D")):
            NodeLink.objects.create(node_a=self.nodes[first], node_b=self.nodes[second])
        node_graph.clear()  # las señales de arriba no cuentan: se prueba la carga desde la base

    def test_it_is_built_from_the_database_on_first_use(self):
        self.assertFalse(node_graph.is_loaded())

        self.assertEqual(node_graph.direct_neighbors("B"), ["A", "C"])

        self.assertTrue(node_graph.is_loaded())

    def test_once_loaded_it_does_not_query_the_database(self):
        node_graph.direct_neighbors("A")

        with self.assertNumQueries(0):
            node_graph.direct_neighbors("B")
            node_graph.neighbors_within("A", 2)

    def test_neighbors_are_symmetric(self):
        self.assertEqual(node_graph.direct_neighbors("A"), ["B"])
        self.assertEqual(node_graph.direct_neighbors("B"), ["A", "C"])

    def test_a_node_without_links_has_no_neighbors(self):
        self.assertEqual(node_graph.direct_neighbors("SOLO"), [])
        self.assertEqual(node_graph.neighbors_within("SOLO", 3), {})

    def test_an_unknown_node_has_no_neighbors(self):
        self.assertEqual(node_graph.direct_neighbors("NO-EXISTE"), [])
        self.assertEqual(node_graph.neighbors_within("NO-EXISTE", 3), {})

    def test_neighbors_within_counts_hops(self):
        self.assertEqual(node_graph.neighbors_within("A", 1), {"B": 1})
        self.assertEqual(node_graph.neighbors_within("A", 2), {"B": 1, "C": 2})
        self.assertEqual(node_graph.neighbors_within("A", 9), {"B": 1, "C": 2, "D": 3})

    def test_a_new_link_updates_a_loaded_graph(self):
        node_graph.direct_neighbors("A")

        NodeLink.objects.create(node_a=self.nodes["SOLO"], node_b=self.nodes["A"])

        self.assertEqual(node_graph.direct_neighbors("A"), ["B", "SOLO"])
        self.assertEqual(node_graph.direct_neighbors("SOLO"), ["A"])

    def test_a_deleted_link_updates_a_loaded_graph(self):
        node_graph.direct_neighbors("A")

        NodeLink.objects.get(node_a=self.nodes["A"], node_b=self.nodes["B"]).delete()

        self.assertEqual(node_graph.direct_neighbors("A"), [])
        self.assertEqual(node_graph.direct_neighbors("B"), ["C"])

    def test_deleting_a_node_removes_its_links_from_the_graph(self):
        node_graph.direct_neighbors("A")

        self.nodes["B"].delete()

        self.assertEqual(node_graph.direct_neighbors("A"), [])
        self.assertEqual(node_graph.direct_neighbors("C"), ["D"])

    def test_signals_do_nothing_while_the_graph_is_not_loaded(self):
        NodeLink.objects.create(node_a=self.nodes["SOLO"], node_b=self.nodes["D"])

        self.assertFalse(node_graph.is_loaded())
        self.assertEqual(node_graph.direct_neighbors("SOLO"), ["D"])

    def test_linked_nodes_lists_only_nodes_with_links(self):
        self.assertEqual(sorted(node_graph.linked_nodes()), ["A", "B", "C", "D"])


@override_settings(PUBLIC_READ_ACCESS=True)
class NodeLinksApiTests(APITestCase):
    def setUp(self):
        node_graph.clear()
        self.addCleanup(node_graph.clear)
        self.nodes = make_nodes("A", "B", "C")
        user = get_user_model().objects.create_user("operador", password="clave-segura-1")
        self.token = Token.objects.create(user=user)

    def url(self, node_id="A"):
        return reverse("node_links", kwargs={"node_id": node_id})

    def authenticate(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def link(self, neighbor, node_id="A"):
        return self.client.post(self.url(node_id), {"neighbor": neighbor}, format="json")

    def test_list_is_public_and_starts_empty(self):
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"node_id": "A", "neighbors": []})

    def test_list_of_an_unknown_node_is_404(self):
        self.assertEqual(self.client.get(self.url("NO-EXISTE")).status_code, status.HTTP_404_NOT_FOUND)

    def test_creating_a_link_requires_authentication(self):
        response = self.link("B")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(NodeLink.objects.count(), 0)

    def test_create_and_list(self):
        self.authenticate()

        response = self.link("B")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data, {"node_id": "A", "neighbor": "B"})
        self.assertEqual(self.client.get(self.url("A")).data["neighbors"], ["B"])
        self.assertEqual(self.client.get(self.url("B")).data["neighbors"], ["A"])

    def test_several_neighbors_are_listed_alphabetically(self):
        self.authenticate()
        self.link("C")
        self.link("B")

        self.assertEqual(self.client.get(self.url("A")).data["neighbors"], ["B", "C"])

    def test_the_same_pair_in_the_other_direction_is_a_conflict(self):
        self.authenticate()
        self.link("B")

        response = self.link("A", node_id="B")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(NodeLink.objects.count(), 1)

    def test_repeating_a_link_is_a_conflict(self):
        self.authenticate()
        self.link("B")

        self.assertEqual(self.link("B").status_code, status.HTTP_409_CONFLICT)

    def test_invalid_neighbors_are_rejected(self):
        self.authenticate()

        for body in ({}, {"neighbor": ""}, {"neighbor": "   "}, {"neighbor": 5},
                     {"neighbor": "A"}, {"neighbor": "NO-EXISTE"}):
            with self.subTest(body=body):
                response = self.client.post(self.url(), body, format="json")

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(NodeLink.objects.count(), 0)

    def test_a_body_that_is_not_an_object_is_rejected(self):
        self.authenticate()

        response = self.client.post(self.url(), ["B"], format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_creating_a_link_for_an_unknown_node_is_404(self):
        self.authenticate()

        self.assertEqual(self.link("B", node_id="NO-EXISTE").status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_removes_the_link_in_both_directions(self):
        self.authenticate()
        self.link("B")

        response = self.client.delete(
            reverse("node_link_detail", kwargs={"node_id": "B", "neighbor_id": "A"})
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(NodeLink.objects.count(), 0)
        self.assertEqual(self.client.get(self.url("A")).data["neighbors"], [])

    def test_delete_requires_authentication_and_an_existing_link(self):
        url = reverse("node_link_detail", kwargs={"node_id": "A", "neighbor_id": "B"})
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_401_UNAUTHORIZED)

        self.authenticate()
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_404_NOT_FOUND)

    def test_listing_does_not_query_the_database_for_links_once_loaded(self):
        self.client.get(self.url("A"))

        with self.assertNumQueries(1):  # solo comprobar que el nodo existe
            self.client.get(self.url("A"))
