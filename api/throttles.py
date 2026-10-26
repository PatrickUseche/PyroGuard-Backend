from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import SimpleRateThrottle


class _IPMethodThrottle(SimpleRateThrottle):
    """Limita por IP solo las peticiones seguras o solo las de escritura."""

    safe_methods = True

    def allow_request(self, request, view):
        if (request.method in SAFE_METHODS) != self.safe_methods:
            return True
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class ReadThrottle(_IPMethodThrottle):
    """Consultas GET, que son públicas."""

    scope = "read"
    safe_methods = True


class LoginThrottle(_IPMethodThrottle):
    """Intentos de inicio de sesión; frena la fuerza bruta de contraseñas."""

    scope = "login"
    safe_methods = False


class IngestThrottle(_IPMethodThrottle):
    """Ingesta POST de lecturas; el límite es holgado para varios nodos por IP."""

    scope = "ingest"
    safe_methods = False
