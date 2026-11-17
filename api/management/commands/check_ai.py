"""Diagnóstico de la conexión con PyroGuard-IA con la configuración del entorno actual.

Uso: ``python manage.py check_ai`` (en Render, desde la pestaña *Shell* o como comando puntual).
No guarda nada: hace un ``GET /health`` y un ``POST /predict`` con una lectura de ejemplo.
Termina con error si la IA está deshabilitada, no responde o rechaza la clave.
"""
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.services.ai_client import SUPPORTED_CONTRACT_MAJOR, auth_headers, health_url, predict_url

SAMPLE_READING = {
    "node_id": "CHECK-AI",
    "temperature": 22.0,
    "humidity": 70.0,
    "smoke": 10.0,
    "gas": 0.0,
    "flame": False,
}


class Command(BaseCommand):
    help = "Comprueba que el backend llega a PyroGuard-IA (/health y /predict) con AI_SERVICE_URL y AI_API_KEY."

    def handle(self, *args, **options):
        if not settings.AI_SERVICE_URL:
            raise CommandError("AI_SERVICE_URL está vacía: la IA está deshabilitada y se evalúa solo con reglas.")

        # Plazo de la ingesta, no el corto de /api/health/: aquí interesa saber si la IA llega a responder.
        timeout = (settings.AI_CONNECT_TIMEOUT, settings.AI_READ_TIMEOUT)
        self.stdout.write(f"AI_SERVICE_URL: {settings.AI_SERVICE_URL}")
        self.stdout.write(f"AI_API_KEY: {'configurada' if settings.AI_API_KEY else 'vacía'}")

        failures = [message for message in (self.check_health(timeout), self.check_predict(timeout)) if message]
        if failures:
            raise CommandError("La IA no está lista: " + "; ".join(failures))
        self.stdout.write(self.style.SUCCESS("La IA responde y acepta la clave del backend."))

    def check_health(self, timeout):
        try:
            response = requests.get(health_url(), timeout=timeout)
        except requests.RequestException as error:
            return self.fail("health", f"sin respuesta ({type(error).__name__})")
        if response.status_code != 200:
            return self.fail("health", f"HTTP {response.status_code} (¿URL con una ruta de más?)")
        body = _json_or_empty(response)
        if body.get("status") != "ok":
            return self.fail("health", f"la IA responde '{body.get('status')}': el modelo no está cargado")
        self.stdout.write(self.style.SUCCESS(f"[OK] health: modelo {body.get('model_version')}"))
        return None

    def check_predict(self, timeout):
        try:
            response = requests.post(predict_url(), json=SAMPLE_READING, headers=auth_headers(), timeout=timeout)
        except requests.RequestException as error:
            return self.fail("predict", f"sin respuesta ({type(error).__name__})")
        if response.status_code in (401, 403):
            return self.fail("predict", "la IA rechazó la clave: AI_API_KEY debe ser igual en los dos servicios")
        if response.status_code != 200:
            return self.fail("predict", f"HTTP {response.status_code}")
        body = _json_or_empty(response)
        contract = str(body.get("contract_version", ""))
        if contract.split(".")[0] != SUPPORTED_CONTRACT_MAJOR:
            return self.fail("predict", f"contrato '{contract}' incompatible (se espera {SUPPORTED_CONTRACT_MAJOR}.x)")
        self.stdout.write(
            self.style.SUCCESS(f"[OK] predict: risk_level={body.get('risk_level')} contrato {contract}")
        )
        return None

    def fail(self, name, message):
        self.stdout.write(self.style.ERROR(f"[FALLA] {name}: {message}"))
        return f"{name}: {message}"


def _json_or_empty(response):
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
