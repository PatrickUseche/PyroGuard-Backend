"""Validaciones de los serializers que la cobertura marcaba sin probar."""
from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError

from .models import Node
from .serializers import JsonBooleanField, NodeSerializer


class JsonBooleanFieldTests(SimpleTestCase):
    def setUp(self):
        self.field = JsonBooleanField()

    def test_booleans_and_binary_integers_are_accepted(self):
        for value, expected in ((True, True), (False, False), (1, True), (0, False)):
            with self.subTest(value=value):
                self.assertIs(self.field.to_internal_value(value), expected)

    def test_other_integers_texts_and_floats_are_rejected(self):
        # Igual que la IA (contrato v1.1): sin coerción de "true", "1" ni 1.0.
        for value in (2, -1, "true", "1", "yes", 1.0, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.field.to_internal_value(value)


class NodeIdValidationTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-S1", name="Norte")

    def test_updating_a_node_keeping_its_id_does_not_clash_with_itself(self):
        serializer = NodeSerializer(self.node, data={"node_id": "NODE-S1", "name": "Norte alto"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_changing_the_id_of_an_existing_node_is_rejected(self):
        serializer = NodeSerializer(self.node, data={"node_id": "NODE-S2"}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("no se puede modificar", str(serializer.errors["node_id"]))

    def test_creating_a_node_with_an_existing_id_is_rejected(self):
        serializer = NodeSerializer(data={"node_id": "NODE-S1"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("node_id", serializer.errors)
