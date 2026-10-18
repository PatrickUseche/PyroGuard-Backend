import hmac
import logging

from django.conf import settings
from rest_framework.permissions import BasePermission, SAFE_METHODS


logger = logging.getLogger("api.permissions")


class IsAuthenticatedOrIngestAPIKey(BasePermission):
    def has_permission(self, request, _view):
        if request.method in SAFE_METHODS:
            return True

        expected_key = settings.INGEST_API_KEY
        supplied_key = request.headers.get("X-API-Key", "")
        if not expected_key:
            if settings.DEBUG:
                logger.warning(
                    "INGEST_API_KEY no está configurada; se permite la ingesta "
                    "en modo DEBUG."
                )
                return True
            self.message = "La ingesta está deshabilitada por falta de configuración."
        elif supplied_key and hmac.compare_digest(
            supplied_key.encode("utf-8"),
            expected_key.encode("utf-8"),
        ):
            return True
        else:
            self.message = "Se requiere una X-API-Key válida para registrar lecturas."

        logger.warning(
            "Solicitud de ingesta rechazada por credenciales ausentes o inválidas."
        )
        return False
