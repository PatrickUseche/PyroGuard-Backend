import math
import os
import re
import secrets
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from config.security import build_security_settings

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default):
    value = os.getenv(name)
    # Vacía equivale a no definida, como en el resto de variables (.env.example).
    if value is None or not value.strip():
        return default

    normalized_value = value.strip().lower()
    if normalized_value in {"true", "1", "yes", "on"}:
        return True
    if normalized_value in {"false", "0", "no", "off"}:
        return False
    raise ValueError(
        f"{name} debe ser un valor booleano válido "
        "(true/false, 1/0, yes/no u on/off)."
    )


def _env_list(name):
    return [
        value.strip()
        for value in os.getenv(name, "").split(",")
        if value.strip()
    ]


def _env_positive_float(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed_value = float(value)
    except ValueError:
        raise ImproperlyConfigured(f"{name} debe ser un número.") from None
    if not math.isfinite(parsed_value) or parsed_value <= 0:
        raise ImproperlyConfigured(f"{name} debe ser un número mayor que 0.")
    return parsed_value


def _env_positive_int(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed_value = int(value)
    except ValueError:
        raise ImproperlyConfigured(f"{name} debe ser un entero.") from None
    if parsed_value < 1:
        raise ImproperlyConfigured(f"{name} debe ser un entero mayor o igual que 1.")
    return parsed_value


def _env_non_negative_float(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed_value = float(value)
    except ValueError:
        raise ImproperlyConfigured(f"{name} debe ser un número.") from None
    if not math.isfinite(parsed_value) or parsed_value < 0:
        raise ImproperlyConfigured(f"{name} debe ser un número mayor o igual que 0.")
    return parsed_value


def _env_rate(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    if not re.fullmatch(r"[1-9]\d*/(sec|min|hour|day)", value):
        raise ImproperlyConfigured(
            f"{name} debe tener el formato N/sec, N/min, N/hour o N/day."
        )
    return value


def _env_non_negative_int(name, default=None):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed_value = int(value)
    except ValueError:
        raise ImproperlyConfigured(f"{name} debe ser un entero.") from None
    if parsed_value < 0:
        raise ImproperlyConfigured(f"{name} no puede ser negativo.")
    return parsed_value


def _env_choice_list(name, choices, default):
    values = _env_list(name)
    if not values:
        return list(default)
    unknown = [value for value in values if value not in choices]
    if unknown:
        raise ImproperlyConfigured(
            f"{name} tiene canales desconocidos: {', '.join(unknown)}. "
            f"Opciones: {', '.join(sorted(choices))}."
        )
    return list(dict.fromkeys(values))


def _env_header_name(name):
    value = os.getenv(name, "").strip()
    if value and not re.fullmatch(r"[A-Za-z0-9]+(-[A-Za-z0-9]+)*", value):
        raise ImproperlyConfigured(
            f"{name} debe ser un nombre de cabecera HTTP, por ejemplo CF-Connecting-IP."
        )
    return value


def _env_service_url(name):
    value = os.getenv(name, "").strip().rstrip("/")
    if value and not value.startswith(("http://", "https://")):
        raise ImproperlyConfigured(f"{name} debe comenzar con http:// o https://.")
    return value


DEBUG = _env_bool("DEBUG", False)
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "La variable SECRET_KEY es obligatoria cuando DEBUG es False."
        )
    SECRET_KEY = secrets.token_urlsafe(50)

# HTTPS, cookies seguras y cabeceras: activos con DEBUG=False (ver config/security.py).
globals().update(build_security_settings(DEBUG))

ALLOWED_HOSTS = [
    ".onrender.com",
    "localhost",
    "127.0.0.1",
    *_env_list("EXTRA_ALLOWED_HOSTS"),
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "rest_framework.authtoken",
    "api",
    "corsheaders",
]

MIDDLEWARE = [
    "api.middleware.RequestIdMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

database_url = os.getenv("DATABASE_URL", "").strip()
if database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            database_url,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation.MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation.CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation.NumericPasswordValidator"
        ),
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:4200",
    "https://pyro-guard-frontend.vercel.app",
    "https://pyro-guard-frontend-im72wci6g-uni-340e.vercel.app",
    *_env_list("EXTRA_CORS_ORIGINS"),
]
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https:\/\/.*\.vercel\.app$",
]
# Sin esto el navegador oculta estas cabeceras al JavaScript del frontend.
CORS_EXPOSE_HEADERS = ["X-Total-Count", "Retry-After", "X-Request-ID"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "api.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "api.throttles.ReadThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "read": _env_rate("THROTTLE_READ_RATE", "120/min"),
        "ingest": _env_rate("THROTTLE_INGEST_RATE", "300/min"),
        "login": _env_rate("THROTTLE_LOGIN_RATE", "10/min"),
        "google_login": "10/min",
    },
    # Saltos de proxy delante de la app; sin valor, DRF toma todo X-Forwarded-For.
    "NUM_PROXIES": _env_non_negative_int("NUM_PROXIES"),
}

# Cabecera con la IP real del cliente que escribe un proxy de confianza (en Render,
# Cloudflare pone CF-Connecting-IP y pisa lo que envíe el cliente). Vacía: se
# usa X-Forwarded-For según NUM_PROXIES.
CLIENT_IP_HEADER = _env_header_name("CLIENT_IP_HEADER")

INGEST_API_KEY = os.getenv("INGEST_API_KEY", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
NODE_OFFLINE_THRESHOLD_SECONDS = int(
    os.getenv("NODE_OFFLINE_THRESHOLD_SECONDS", "300")
)
ALERT_ON_WARNING = _env_bool("ALERT_ON_WARNING", False)
AUTO_REGISTER_NODES = _env_bool("AUTO_REGISTER_NODES", False)
# Con False, las consultas GET también exigen token (para cuando el frontend tenga login).
PUBLIC_READ_ACCESS = _env_bool("PUBLIC_READ_ACCESS", True)
# Cuántas lecturas recientes guarda en memoria cada nodo (ver services/live_readings.py).
RECENT_READINGS_PER_NODE = _env_positive_int("RECENT_READINGS_PER_NODE", 50)
# Cuántas lecturas cubre la ventana de temperatura máxima y mínima de cada nodo.
TEMPERATURE_WINDOW_SIZE = _env_positive_int("TEMPERATURE_WINDOW_SIZE", 20)
# Nodos cuyo /status/ se guarda en la caché LRU (0 la desactiva).
NODE_STATUS_CACHE_SIZE = _env_non_negative_int("NODE_STATUS_CACHE_SIZE", 256)
# Segundos que se reutiliza el resumen de /dashboard/summary/ (0 lo desactiva).
DASHBOARD_CACHE_SECONDS = _env_non_negative_float("DASHBOARD_CACHE_SECONDS", 5.0)
# Descarta las lecturas repetidas (mismo nodo y mismo timestamp) con un filtro de Bloom.
DEDUPLICATE_READINGS = _env_bool("DEDUPLICATE_READINGS", True)
# Cuántos saltos hacia los vecinos se avisa cuando un nodo entra en FIRE (0 lo desactiva).
NEIGHBOR_WARNING_HOPS = _env_non_negative_int("NEIGHBOR_WARNING_HOPS", 2)
# Días que se conservan las lecturas antes de que `purge_readings` las borre.
READINGS_RETENTION_DAYS = _env_positive_int("READINGS_RETENTION_DAYS", 90)

# Notificaciones (ver api/notifications). Canales: console, email y telegram.
NOTIFICATION_CHANNELS = _env_choice_list(
    "NOTIFICATION_CHANNELS", {"console", "email", "telegram"}, default=["console"]
)
NOTIFY_EMAIL_TO = _env_list("NOTIFY_EMAIL_TO")
# Intentos de envío antes de dar un aviso por fallido.
NOTIFICATION_MAX_ATTEMPTS = _env_positive_int("NOTIFICATION_MAX_ATTEMPTS", 3)
# Segundos durante los que no se repite el mismo aviso del mismo nodo (0 lo desactiva).
NOTIFICATION_COOLDOWN_SECONDS = _env_non_negative_int("NOTIFICATION_COOLDOWN_SECONDS", 300)
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = _env_positive_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "pyroguard@localhost")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
# Lecturas que recuerda el filtro antes de reiniciarse (ver services/duplicate_readings.py).
DUPLICATE_FILTER_CAPACITY = _env_positive_int("DUPLICATE_FILTER_CAPACITY", 100000)

# Servicio PyroGuard-IA (contrato v1.0). Sin URL, la IA queda deshabilitada y
# el riesgo se evalúa solo con las reglas del backend.
AI_SERVICE_URL = _env_service_url("AI_SERVICE_URL")
# Conexión corta para detectar rápido un servicio caído; lectura más amplia
# para dar tiempo a la inferencia.
AI_CONNECT_TIMEOUT = _env_positive_float("AI_CONNECT_TIMEOUT", 3.0)
AI_READ_TIMEOUT = _env_positive_float("AI_READ_TIMEOUT", 10.0)
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
# Con True la ingesta no espera a la IA: guarda la lectura con las reglas y deja la
# evaluación de la IA pendiente para `manage.py drain_ai_queue`.
AI_ASYNC_EVALUATION = _env_bool("AI_ASYNC_EVALUATION", False)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
# "text" (legible, por defecto) o "json" (una línea JSON por registro, para agregadores de logs).
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").strip().lower() or "text"
if LOG_FORMAT not in {"text", "json"}:
    raise ImproperlyConfigured("LOG_FORMAT debe ser 'text' o 'json'.")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "api.logging_utils.RequestIdFilter"},
    },
    "formatters": {
        "text": {
            "format": "{levelname} {asctime} {name} [{request_id}]: {message}",
            "style": "{",
        },
        "json": {"()": "api.logging_utils.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "api": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PyroGuard API",
    "DESCRIPTION": (
        "Backend de PyroGuard: ingesta de lecturas de sensores, evaluación de riesgo de incendio "
        "(reglas + IA), alertas, notificaciones y estado de los nodos."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["api.permissions.IsAuthenticatedOrPublicRead"],
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "RiskLevelEnum": "api.openapi.RISK_LEVELS",
        "AtRiskLevelEnum": "api.openapi.AT_RISK_LEVELS",
        "ConnectionStatusEnum": "api.openapi.CONNECTION_STATES",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
