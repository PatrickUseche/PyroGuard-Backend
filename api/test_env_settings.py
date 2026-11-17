"""Lectura de variables de entorno numéricas de `config/settings.py`."""
import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import _env_non_negative_float, _env_positive_int


class PositiveIntSettingTests(SimpleTestCase):
    def test_empty_uses_the_default_and_valid_values_are_parsed(self):
        with patch.dict(os.environ, {"PRUEBA_INT": ""}):
            self.assertEqual(_env_positive_int("PRUEBA_INT", 7), 7)
        with patch.dict(os.environ, {"PRUEBA_INT": " 25 "}):
            self.assertEqual(_env_positive_int("PRUEBA_INT", 7), 25)

    def test_non_integers_and_values_below_one_are_rejected(self):
        cases = (("abc", "un entero"), ("2.5", "un entero"), ("0", "mayor o igual que 1"), ("-3", "mayor"))
        for value, message in cases:
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"PRUEBA_INT": value}),
                self.assertRaisesMessage(ImproperlyConfigured, message),
            ):
                _env_positive_int("PRUEBA_INT", 7)


class NonNegativeFloatSettingTests(SimpleTestCase):
    def test_zero_and_positive_values_are_accepted(self):
        for value, expected in (("0", 0.0), ("1.5", 1.5), ("", 3.0)):
            with self.subTest(value=value), patch.dict(os.environ, {"PRUEBA_FLOAT": value}):
                self.assertEqual(_env_non_negative_float("PRUEBA_FLOAT", 3.0), expected)

    def test_text_negative_and_non_finite_values_are_rejected(self):
        for value in ("rápido", "-0.1", "nan", "inf"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"PRUEBA_FLOAT": value}),
                self.assertRaisesMessage(ImproperlyConfigured, "PRUEBA_FLOAT"),
            ):
                _env_non_negative_float("PRUEBA_FLOAT", 3.0)
