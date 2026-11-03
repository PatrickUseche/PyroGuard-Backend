"""render.yaml debe ser coherente con el código: comandos, ruta de salud y variables que existen."""
from pathlib import Path

import yaml
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve

BLUEPRINT = yaml.safe_load((Path(settings.BASE_DIR) / "render.yaml").read_text(encoding="utf-8"))


class RenderBlueprintTests(SimpleTestCase):
    def setUp(self):
        self.web = next(s for s in BLUEPRINT["services"] if s["type"] == "web")
        self.env = {item["key"]: item for item in self.web["envVars"]}

    def test_health_check_path_exists(self):
        resolve(self.web["healthCheckPath"])

    def test_build_migrates_and_collects_static(self):
        self.assertIn("migrate --noinput", self.web["buildCommand"])
        self.assertIn("collectstatic --noinput", self.web["buildCommand"])

    def test_single_worker_because_state_is_in_memory(self):
        self.assertIn("--workers 1", self.web["startCommand"])

    def test_database_is_linked_and_declared(self):
        self.assertEqual(self.env["DATABASE_URL"]["fromDatabase"]["name"], BLUEPRINT["databases"][0]["name"])

    def test_secrets_are_generated_not_written(self):
        for key in ("SECRET_KEY", "INGEST_API_KEY"):
            self.assertTrue(self.env[key].get("generateValue"))
            self.assertNotIn("value", self.env[key])

    def test_production_mode(self):
        self.assertEqual(self.env["DEBUG"]["value"], "False")
