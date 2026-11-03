"""Ajustes de seguridad para producción (HTTPS, cookies y cabeceras).

Con ``DEBUG=True`` (desarrollo y pruebas) todo queda como Django lo trae, para poder trabajar por
``http://localhost``. Con ``DEBUG=False`` se activa el endurecimiento. Cada ajuste se puede cambiar
con una variable de entorno; las cabeceras y cookies se corrigen sin tocar código.

Render termina el HTTPS en su proxy y reenvía la petición por HTTP con ``X-Forwarded-Proto: https``,
por eso se confía en esa cabecera: sin ella, ``SECURE_SSL_REDIRECT`` redirigiría en bucle.
"""
import os

from django.core.exceptions import ImproperlyConfigured


def _bool(name, default):
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} debe ser un valor booleano válido (true/false, 1/0, yes/no u on/off).")


def _non_negative_int(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise ImproperlyConfigured(f"{name} debe ser un entero.") from None
    if parsed < 0:
        raise ImproperlyConfigured(f"{name} no puede ser negativo.")
    return parsed


#: Un mes: lo bastante largo para que sirva y lo bastante corto para poder deshacerlo si algo falla.
DEFAULT_HSTS_SECONDS = 60 * 60 * 24 * 30


def build_security_settings(debug):
    """Devuelve el diccionario de ajustes ``SECURE_*``, cookies y cabeceras."""
    production = not debug
    return {
        # Se obedece X-Forwarded-Proto del proxy para saber si la petición original era HTTPS.
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https") if production else None,
        "SECURE_SSL_REDIRECT": _bool("SECURE_SSL_REDIRECT", production),
        # Los chequeos de salud de la plataforma suelen llegar sin HTTPS: no se redirigen.
        "SECURE_REDIRECT_EXEMPT": [r"^api/health/$"],
        "SESSION_COOKIE_SECURE": _bool("SESSION_COOKIE_SECURE", production),
        "CSRF_COOKIE_SECURE": _bool("CSRF_COOKIE_SECURE", production),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "CSRF_COOKIE_SAMESITE": "Lax",
        "SECURE_HSTS_SECONDS": _non_negative_int(
            "SECURE_HSTS_SECONDS", DEFAULT_HSTS_SECONDS if production else 0
        ),
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": _bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False),
        "SECURE_HSTS_PRELOAD": _bool("SECURE_HSTS_PRELOAD", False),
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_REFERRER_POLICY": "same-origin",
        "X_FRAME_OPTIONS": "DENY",
    }
