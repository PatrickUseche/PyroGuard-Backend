import hmac
import logging

from django.conf import settings
from rest_framework.permissions import BasePermission, SAFE_METHODS


logger = logging.getLogger("api.permissions")


def _is_authenticated(request):
    return bool(request.user and request.user.is_authenticated)


class IsAuthenticatedOrPublicRead(BasePermission):
    """Las lecturas son públicas salvo que PUBLIC_READ_ACCESS sea False."""

    def has_permission(self, request, _view):
        if request.method in SAFE_METHODS and settings.PUBLIC_READ_ACCESS:
            return True
        return _is_authenticated(request)


class IsAuthenticatedOrIngestAPIKey(BasePermission):
    def has_permission(self, request, _view):
        if request.method in SAFE_METHODS:
            return settings.PUBLIC_READ_ACCESS or _is_authenticated(request)

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
