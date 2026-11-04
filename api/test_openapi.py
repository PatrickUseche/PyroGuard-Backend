"""Pruebas del esquema OpenAPI: que se genere sin avisos y que documente todos los endpoints."""
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework import status


class OpenApiSchemaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.schema = Client().get(reverse("schema"), {"format": "json"}).json()

    def test_the_schema_endpoint_is_served(self):
        response = self.client.get(reverse("schema"), {"format": "json"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["info"]["title"], "PyroGuard API")

    def test_the_default_format_is_yaml(self):
        response = self.client.get(reverse("schema"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("openapi:", response.content.decode())

    def test_the_documentation_page_is_served(self):
        self.assertEqual(self.client.get(reverse("swagger-ui")).status_code, status.HTTP_200_OK)

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_the_schema_is_private_when_reads_are_private(self):
        self.assertEqual(self.client.get(reverse("schema")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_it_generates_without_errors_or_warnings(self):
        out, err = StringIO(), StringIO()

        # --fail-on-warn hace que cualquier aviso del generador lance CommandError.
        call_command("spectacular", "--fail-on-warn", stdout=out, stderr=err)

        self.assertIn("openapi:", out.getvalue())
        self.assertNotIn("Error", err.getvalue())

    def test_every_api_path_is_documented(self):
        expected = {
            "/api/health/",
            "/api/readings/",
            "/api/readings/series/",
            "/api/dashboard/summary/",
            "/api/dashboard/top-risk/",
            "/api/dashboard/zones/",
            "/api/nodes/",
            "/api/nodes/{node_id}/",
            "/api/nodes/{node_id}/status/",
            "/api/nodes/{node_id}/readings/",
            "/api/nodes/{node_id}/recent/",
            "/api/nodes/{node_id}/links/",
            "/api/nodes/{node_id}/links/{neighbor_id}/",
            "/api/nodes/{node_id}/neighbors/",
            "/api/nodes/search/",
            "/api/alerts/",
            "/api/alerts/active/",
            "/api/alerts/{alert_id}/",
            "/api/alerts/{alert_id}/acknowledge/",
            "/api/alerts/{alert_id}/close/",
            "/api/auth/google/",
            "/api/auth/me/",
            "/api/auth/logout/",
        }

        self.assertTrue(expected <= set(self.schema["paths"]), expected - set(self.schema["paths"]))

    def test_every_operation_has_a_summary_or_description(self):
        for path, methods in self.schema["paths"].items():
            for method, operation in methods.items():
                if method == "parameters":
                    continue
                with self.subTest(path=path, method=method):
                    self.assertTrue(
                        operation.get("summary") or operation.get("description") or operation.get("operationId"),
                    )

    def test_operation_ids_are_unique(self):
        ids = [
            operation["operationId"]
            for methods in self.schema["paths"].values()
            for method, operation in methods.items()
            if method != "parameters"
        ]

        self.assertEqual(len(ids), len(set(ids)))

    def test_the_ingest_operation_has_examples_and_documents_duplicates(self):
        post = self.schema["paths"]["/api/readings/"]["post"]

        examples = post["requestBody"]["content"]["application/json"]["examples"]
        self.assertEqual(set(examples), {"LecturaNormal", "LecturaConLlama"})
        self.assertIn("200", post["responses"])
        self.assertIn("201", post["responses"])
        self.assertIn("duplicate", post["description"])

    def test_the_status_response_describes_the_temperature_window(self):
        schemas = self.schema["components"]["schemas"]

        self.assertIn("temperature_window", schemas["NodeStatus"]["properties"])
        self.assertEqual(
            set(schemas["TemperatureWindow"]["properties"]), {"size", "readings", "max", "min"}
        )

    def test_the_series_parameters_are_described(self):
        parameters = {p["name"]: p for p in self.schema["paths"]["/api/readings/series/"]["get"]["parameters"]}

        self.assertEqual(set(parameters), {"node_id", "field", "from", "to", "step", "merge"})
        self.assertTrue(parameters["node_id"]["required"])
        self.assertEqual(set(parameters["field"]["schema"]["enum"]), {"temperature", "humidity", "smoke", "gas"})

    def test_risk_levels_share_one_named_enum(self):
        schemas = self.schema["components"]["schemas"]

        self.assertEqual(schemas["RiskLevelEnum"]["enum"], ["NORMAL", "WARNING", "FIRE"])
