"""Validaciones de los serializers que la cobertura marcaba sin probar."""
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from .serializers import JsonBooleanField


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

