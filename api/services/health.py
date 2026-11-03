"""Estado de salud del backend y de sus dependencias (``GET /api/health/``)."""
import logging
import time

from django.db import connection

logger = logging.getLogger("api.health")


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


def get_health():
    """Devuelve ``(cuerpo, código HTTP)``: 200 si la base responde y 503 si no."""
    database = check_database()
    if database["status"] != "ok":
        return {"status": "down", "database": database}, 503
    return {"status": "ok", "database": database}, 200
