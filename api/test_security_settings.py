"""Pruebas de los ajustes de seguridad de producción (config/security.py)."""
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from config.security import DEFAULT_HSTS_SECONDS, build_security_settings

BASE_DIR = Path(__file__).resolve().parent.parent
SECURITY_ENV = [
    "SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", "SECURE_HSTS_PRELOAD",
]


def build(debug, **env):
    cleaned = {name: "" for name in SECURITY_ENV}
    cleaned.update(env)
    with patch.dict(os.environ, cleaned):
        return build_security_settings(debug)


class DevelopmentSettingsTests(SimpleTestCase):
    def test_nothing_is_forced_in_development(self):
        config = build(debug=True)

        self.assertFalse(config["SECURE_SSL_REDIRECT"])
        self.assertFalse(config["SESSION_COOKIE_SECURE"])
        self.assertFalse(config["CSRF_COOKIE_SECURE"])
        self.assertEqual(config["SECURE_HSTS_SECONDS"], 0)
        self.assertIsNone(config["SECURE_PROXY_SSL_HEADER"])

    def test_the_header_hardening_applies_everywhere(self):
        for debug in (True, False):
            config = build(debug=debug)
            self.assertTrue(config["SECURE_CONTENT_TYPE_NOSNIFF"])
            self.assertEqual(config["X_FRAME_OPTIONS"], "DENY")
            self.assertEqual(config["SECURE_REFERRER_POLICY"], "same-origin")
            self.assertTrue(config["SESSION_COOKIE_HTTPONLY"])
            self.assertEqual(config["SESSION_COOKIE_SAMESITE"], "Lax")
            self.assertEqual(config["CSRF_COOKIE_SAMESITE"], "Lax")


class ProductionSettingsTests(SimpleTestCase):
    def test_https_is_enforced_by_default(self):
        config = build(debug=False)

        self.assertTrue(config["SECURE_SSL_REDIRECT"])
        self.assertTrue(config["SESSION_COOKIE_SECURE"])
        self.assertTrue(config["CSRF_COOKIE_SECURE"])

    def test_the_proxy_header_is_trusted_so_render_does_not_loop(self):
        self.assertEqual(
            build(debug=False)["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https")
        )

    def test_hsts_is_on_for_a_month_without_subdomains_or_preload(self):
        config = build(debug=False)

        self.assertEqual(config["SECURE_HSTS_SECONDS"], DEFAULT_HSTS_SECONDS)
        self.assertEqual(DEFAULT_HSTS_SECONDS, 30 * 24 * 3600)
        self.assertFalse(config["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertFalse(config["SECURE_HSTS_PRELOAD"])

    def test_the_health_check_is_exempt_from_the_redirect(self):
        self.assertEqual(build(debug=False)["SECURE_REDIRECT_EXEMPT"], [r"^api/health/$"])


class EnvironmentOverrideTests(SimpleTestCase):
    def test_each_setting_can_be_turned_off(self):
        config = build(
            debug=False, SECURE_SSL_REDIRECT="false", SESSION_COOKIE_SECURE="0", CSRF_COOKIE_SECURE="no",
        )

        self.assertFalse(config["SECURE_SSL_REDIRECT"])
        self.assertFalse(config["SESSION_COOKIE_SECURE"])
        self.assertFalse(config["CSRF_COOKIE_SECURE"])

    def test_they_can_be_turned_on_in_development_to_try_them(self):
        config = build(debug=True, SECURE_SSL_REDIRECT="true", SESSION_COOKIE_SECURE="on")

        self.assertTrue(config["SECURE_SSL_REDIRECT"])
        self.assertTrue(config["SESSION_COOKIE_SECURE"])

    def test_hsts_can_be_changed_or_disabled(self):
        self.assertEqual(build(debug=False, SECURE_HSTS_SECONDS="31536000")["SECURE_HSTS_SECONDS"], 31536000)
        self.assertEqual(build(debug=False, SECURE_HSTS_SECONDS="0")["SECURE_HSTS_SECONDS"], 0)

    def test_subdomains_and_preload_can_be_enabled(self):
        config = build(debug=False, SECURE_HSTS_INCLUDE_SUBDOMAINS="true", SECURE_HSTS_PRELOAD="true")

        self.assertTrue(config["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertTrue(config["SECURE_HSTS_PRELOAD"])

    def test_an_empty_value_means_the_default(self):
        self.assertTrue(build(debug=False, SECURE_SSL_REDIRECT="  ")["SECURE_SSL_REDIRECT"])

    def test_invalid_values_stop_the_startup(self):
        for env in ({"SECURE_SSL_REDIRECT": "quizá"}, {"SECURE_HSTS_SECONDS": "mucho"},
                    {"SECURE_HSTS_SECONDS": "-1"}, {"CSRF_COOKIE_SECURE": "2"}):
            with self.subTest(env=env), self.assertRaises(ImproperlyConfigured):
                build(debug=False, **env)


class DeployedBehaviourTests(TestCase):
    """Con los ajustes de producción aplicados a Django (como en Render)."""

    PRODUCTION = dict(
        SECURE_SSL_REDIRECT=True,
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        SECURE_HSTS_SECONDS=DEFAULT_HSTS_SECONDS,
        SECURE_REDIRECT_EXEMPT=[r"^api/health/$"],
        SESSION_COOKIE_SECURE=True,
        ALLOWED_HOSTS=["testserver"],
    )

    def test_plain_http_is_redirected_to_https(self):
        with override_settings(**self.PRODUCTION):
            response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://testserver/api/dashboard/summary/")

    def test_a_request_the_proxy_marked_as_https_is_served_with_hsts(self):
        with override_settings(**self.PRODUCTION):
            response = self.client.get(reverse("dashboard_summary"), headers={"x-forwarded-proto": "https"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Strict-Transport-Security"], f"max-age={DEFAULT_HSTS_SECONDS}")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_the_health_check_is_never_redirected(self):
        with override_settings(**self.PRODUCTION, AI_SERVICE_URL=""):
            response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)

    def test_the_current_settings_do_not_redirect_in_tests(self):
        response = self.client.get(reverse("dashboard_summary"))

        self.assertEqual(response.status_code, 200)


class CheckDeployTests(SimpleTestCase):
    # Decisiones conscientes: subdominios y preload solo se activan si el dominio lo permite.
    ACCEPTED = {"security.W005", "security.W021"}

    def test_django_check_deploy_only_reports_the_accepted_warnings(self):
        env = {
            **os.environ,
            "DEBUG": "False",
            "SECRET_KEY": "x" * 60 + "-clave-de-prueba-para-check-deploy-sin-prefijo-inseguro",
            "DATABASE_URL": "",
            "AI_SERVICE_URL": "",
        }
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy"],
            cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=120,
        )

        reported = set(re.findall(r"security\.W\d+", result.stdout + result.stderr))
        self.assertEqual(reported - self.ACCEPTED, set(), result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0)
