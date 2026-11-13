"""Los 404 de la API usan un mensaje en español, como el resto de los errores."""
from rest_framework import status
from rest_framework.test import APITestCase

from .exceptions import NOT_FOUND_MESSAGE


class NotFoundMessageTests(APITestCase):
    def test_unknown_node_is_answered_in_spanish(self):
        response = self.client.get("/api/nodes/NO-EXISTE/status/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["status"], "error")
        self.assertEqual(response.data["errors"]["detail"], NOT_FOUND_MESSAGE)

    def test_the_english_django_message_is_not_exposed(self):
        response = self.client.get("/api/nodes/NO-EXISTE/recent/")

        self.assertNotIn("matches the given query", str(response.data))

    def test_an_unknown_api_route_is_answered_in_json_not_html(self):
        response = self.client.get("/api/no-existe/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["errors"]["detail"], NOT_FOUND_MESSAGE)

    def test_known_routes_are_not_affected_by_the_catch_all(self):
        self.assertEqual(self.client.get("/api/health/").status_code, status.HTTP_200_OK)
