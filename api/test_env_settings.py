"""Lectura de variables de entorno numéricas de `config/settings.py`."""
import json
import os
import subprocess
import sys
from unittest.mock import patch

from django.conf import settings
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


class SecretKeySettingTests(SimpleTestCase):
    """Sin SECRET_KEY el backend solo arranca en desarrollo (DEBUG=True), con una clave aleatoria.

    Se importa `config.settings` en un proceso aparte para no alterar los ajustes de esta ejecución.
    """

    def import_settings(self, debug):
        # SECRET_KEY vacía (no ausente) para que un `.env` local no la rellene:
        # load_dotenv no pisa variables ya definidas.
        env = {**os.environ, "SECRET_KEY": "", "DEBUG": debug, "DATABASE_URL": "", "AI_SERVICE_URL": ""}
        code = "import config.settings as s; print(len(s.SECRET_KEY))"
        return subprocess.run(
            [sys.executable, "-c", code], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60
        )

    def test_production_without_secret_key_refuses_to_start(self):
        result = self.import_settings("False")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY es obligatoria", result.stderr)

    def test_development_without_secret_key_generates_one(self):
        result = self.import_settings("True")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(int(result.stdout.strip()), 50)


class DatabaseUrlSettingTests(SimpleTestCase):
    def test_database_url_selects_postgres_with_persistent_connections(self):
        env = {
            **os.environ,
            "DEBUG": "True",
            "DATABASE_URL": "postgres://usuario:clave@db.ejemplo:5432/pyroguard",
            "AI_SERVICE_URL": "",
        }
        code = (
            "import json, config.settings as s; d = s.DATABASES['default']; "
            "print(json.dumps([d['ENGINE'], d['NAME'], d['HOST'], d['PORT'], d['CONN_MAX_AGE']]))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        engine, name, host, port, conn_max_age = json.loads(result.stdout)
        self.assertEqual(engine, "django.db.backends.postgresql")
        self.assertEqual((name, host, port), ("pyroguard", "db.ejemplo", 5432))
        self.assertGreater(conn_max_age, 0)
