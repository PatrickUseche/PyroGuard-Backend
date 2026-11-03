"""Pruebas del formato JSON de los logs y del request_id."""
import io
import json
import logging
import os
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .logging_utils import JsonFormatter, RequestIdFilter, request_id_var
from .middleware import REQUEST_ID_HEADER


def capture(formatter, logger_name="api.test"):
    """Devuelve (logger, stream) con un handler que usa ``formatter`` y el filtro de request_id."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    logger = logging.getLogger(logger_name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, stream


class JsonFormatterTests(SimpleTestCase):
    def tearDown(self):
        logging.getLogger("api.test").handlers = []

    def line(self, stream):
        return json.loads(stream.getvalue().strip().splitlines()[-1])

    def test_each_record_is_one_json_line_with_the_basic_fields(self):
        logger, stream = capture(JsonFormatter())

        logger.info("Lectura recibida node_id=%s", "SIM-001")

        self.assertEqual(len(stream.getvalue().strip().splitlines()), 1)
        entry = self.line(stream)
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["logger"], "api.test")
        self.assertEqual(entry["message"], "Lectura recibida node_id=SIM-001")
        self.assertEqual(entry["request_id"], "-")
        self.assertRegex(entry["time"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$")

    def test_non_ascii_text_is_kept_readable(self):
        logger, stream = capture(JsonFormatter())

        logger.warning("Llama detectada en el nodo ñandú")

        self.assertIn("ñandú", stream.getvalue())

    def test_a_message_with_newlines_stays_on_one_line(self):
        logger, stream = capture(JsonFormatter())

        logger.info("primera\nsegunda\nFalso log injection")

        self.assertEqual(len(stream.getvalue().strip().splitlines()), 1)
        self.assertEqual(self.line(stream)["message"], "primera\nsegunda\nFalso log injection")

    def test_exceptions_are_included(self):
        logger, stream = capture(JsonFormatter())

        try:
            raise ValueError("fallo de prueba")
        except ValueError:
            logger.exception("Algo falló")

        entry = self.line(stream)
        self.assertEqual(entry["level"], "ERROR")
        self.assertIn("ValueError: fallo de prueba", entry["exception"])
        self.assertIn("Traceback", entry["exception"])

    def test_extra_fields_are_added(self):
        logger, stream = capture(JsonFormatter())

        logger.info("Con extras", extra={"node_id": "SIM-001", "attempt": 2})

        entry = self.line(stream)
        self.assertEqual((entry["node_id"], entry["attempt"]), ("SIM-001", 2))

    def test_values_that_are_not_json_serializable_are_converted(self):
        logger, stream = capture(JsonFormatter())

        logger.info("Con objeto", extra={"conjunto": {1, 2}})

        self.assertIsInstance(self.line(stream)["conjunto"], str)

    def test_it_uses_the_request_id_of_the_current_request(self):
        logger, stream = capture(JsonFormatter())
        token = request_id_var.set("abc123")
        self.addCleanup(request_id_var.reset, token)

        logger.info("Dentro de una petición")

        self.assertEqual(self.line(stream)["request_id"], "abc123")

    def test_standard_record_attributes_are_not_repeated(self):
        logger, stream = capture(JsonFormatter())

        logger.info("Solo lo esencial")

        entry = self.line(stream)
        self.assertEqual(set(entry), {"time", "level", "logger", "message", "request_id"})


class LoggingSettingsTests(SimpleTestCase):
    def test_the_console_handler_adds_the_request_id(self):
        handler = settings.LOGGING["handlers"]["console"]

        self.assertIn("request_id", handler["filters"])
        self.assertIn("request_id", settings.LOGGING["filters"])

    def test_the_text_format_shows_the_request_id(self):
        self.assertIn("{request_id}", settings.LOGGING["formatters"]["text"]["format"])

    def test_both_formats_are_defined(self):
        self.assertEqual(set(settings.LOGGING["formatters"]), {"text", "json"})

    def test_an_invalid_log_format_stops_the_startup(self):
        import importlib

        from config import settings as settings_module

        with patch.dict(os.environ, {"LOG_FORMAT": "xml"}):
            with self.assertRaises(ImproperlyConfigured):
                try:
                    importlib.reload(settings_module)
                finally:
                    os.environ.pop("LOG_FORMAT", None)
                    importlib.reload(settings_module)


class RequestIdMiddlewareTests(TestCase):
    def get(self, **headers):
        return self.client.get(reverse("dashboard_summary"), **headers)

    def test_every_response_has_a_generated_request_id(self):
        response = self.get()

        request_id = response[REQUEST_ID_HEADER]
        self.assertRegex(request_id, r"^[0-9a-f]{32}$")

    def test_each_request_gets_a_different_id(self):
        self.assertNotEqual(self.get()[REQUEST_ID_HEADER], self.get()[REQUEST_ID_HEADER])

    def test_a_valid_id_from_the_client_is_reused(self):
        response = self.get(HTTP_X_REQUEST_ID="mi-peticion_01.a")

        self.assertEqual(response[REQUEST_ID_HEADER], "mi-peticion_01.a")

    def test_invalid_ids_are_replaced(self):
        for supplied in ("con espacios", "x" * 65, "a;b", "línea\nnueva", "<script>"):
            with self.subTest(supplied=supplied):
                response = self.get(HTTP_X_REQUEST_ID=supplied)

                self.assertRegex(response[REQUEST_ID_HEADER], r"^[0-9a-f]{32}$")

    def test_error_responses_also_carry_the_id(self):
        response = self.client.get(reverse("node_status", kwargs={"node_id": "NO-EXISTE"}))

        self.assertEqual(response.status_code, 404)
        self.assertIn(REQUEST_ID_HEADER, response)

    def test_the_logs_of_a_request_carry_its_id(self):
        logger, stream = capture(JsonFormatter(), logger_name="api.readings")
        self.addCleanup(setattr, logger, "handlers", [])

        self.client.get(
            reverse("receive_reading"),
            {"limit": "999999"},  # paginación inválida: registra una advertencia en api.readings
            HTTP_X_REQUEST_ID="trace-42",
        )

        entries = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
        self.assertTrue(entries)
        self.assertTrue(all(entry["request_id"] == "trace-42" for entry in entries))

    def test_framework_error_logs_carry_the_id_too(self):
        logger, stream = capture(JsonFormatter(), logger_name="django.request")
        self.addCleanup(setattr, logger, "handlers", [])
        self.addCleanup(setattr, logger, "propagate", True)

        self.client.get(reverse("node_status", kwargs={"node_id": "NO-EXISTE"}), HTTP_X_REQUEST_ID="trace-404")

        entries = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
        self.assertTrue(any("Not Found" in e["message"] and e["request_id"] == "trace-404" for e in entries))

    def test_the_id_does_not_leak_into_the_next_request(self):
        self.get(HTTP_X_REQUEST_ID="primera")

        self.assertEqual(request_id_var.get(), "-")

    def test_it_is_the_first_middleware(self):
        self.assertEqual(settings.MIDDLEWARE[0], "api.middleware.RequestIdMiddleware")

    def test_cors_exposes_the_header(self):
        self.assertIn("X-Request-ID", settings.CORS_EXPOSE_HEADERS)
