import ipaddress

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import SimpleRateThrottle


def _header_ip(request, header):
    meta_key = "HTTP_" + header.upper().replace("-", "_")
    value = request.META.get(meta_key, "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


class _IPMethodThrottle(SimpleRateThrottle):
    """Limita por IP solo las peticiones seguras o solo las de escritura."""

    safe_methods = True

    def allow_request(self, request, view):
        if (request.method in SAFE_METHODS) != self.safe_methods:
            return True
        return super().allow_request(request, view)

    def get_ident(self, request):
        header = settings.CLIENT_IP_HEADER
        if not header:
            return super().get_ident(request)
        # Con la cabecera de confianza configurada no se mira X-Forwarded-For,
        # que el cliente puede falsear; sin una IP válida se usa la del socket.
        return _header_ip(request, header) or request.META.get("REMOTE_ADDR")

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class ReadThrottle(_IPMethodThrottle):
    """Consultas GET, que son públicas."""

    scope = "read"
    safe_methods = True


class GoogleLoginThrottle(_IPMethodThrottle):
    """Limita por IP los intentos de acceso con Google."""

    scope = "google_login"
    safe_methods = False


class GoogleRegisterThrottle(_IPMethodThrottle):
    """Limita por IP los intentos de registro con Google."""

    scope = "google_register"
    safe_methods = False


class IngestThrottle(_IPMethodThrottle):
    """Ingesta POST de lecturas; el límite es holgado para varios nodos por IP."""

    scope = "ingest"
    safe_methods = False
