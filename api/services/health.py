"""Estado de salud del backend y de sus dependencias (``GET /api/health/``)."""
import logging
import time

import requests
from django.conf import settings
from django.db import connection

logger = logging.getLogger("api.health")

AI_HEALTH_TIMEOUT_SECONDS = 2.0


def check_database():
    """Ejecuta una consulta mínima y mide cuánto tarda."""
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as error:  # noqa: BLE001 - cualquier fallo de la base significa "caída"
        logger.error("La base de datos no responde (%s).", type(error).__name__)
        return {"status": "down"}
    return {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def check_ai():
    """Consulta ``/health`` de PyroGuard-IA con un timeout corto (no frena al sensor ni al frontend)."""
    if not settings.AI_SERVICE_URL:
        return {"status": "disabled"}
    started = time.perf_counter()
    try:
        response = requests.get(f"{settings.AI_SERVICE_URL}/health", timeout=AI_HEALTH_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        logger.warning("La IA no responde a /health (%s).", type(error).__name__)
        return {"status": "unavailable"}
    if response.status_code != 200:
        logger.warning("La IA respondió HTTP %s a /health.", response.status_code)
        return {"status": "unavailable"}
    return {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def get_health():
    """Devuelve ``(cuerpo, código HTTP)``.

    * ``ok``: todo responde (la IA puede estar deshabilitada por configuración).
    * ``degraded``: la base responde pero la IA configurada no; el backend sigue
      funcionando solo con las reglas, así que el código HTTP es 200.
    * ``down``: la base no responde; el código HTTP es 503.
    """
    database = check_database()
    if database["status"] != "ok":
        return {"status": "down", "database": database, "ai": {"status": "not_checked"}}, 503
    ai = check_ai()
    overall = "degraded" if ai["status"] == "unavailable" else "ok"
    return {"status": overall, "database": database, "ai": ai}, 200
