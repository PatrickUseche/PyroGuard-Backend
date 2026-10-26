import math
import os
import re
import secrets
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


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


def _env_rate(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    if not re.fullmatch(r"[1-9]\d*/(sec|min|hour|day)", value):
        raise ImproperlyConfigured(
            f"{name} debe tener el formato N/sec, N/min, N/hour o N/day."
        )
    return value


def _env_non_negative_int(name):
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        parsed_value = int(value)
    except ValueError:
        raise ImproperlyConfigured(f"{name} debe ser un entero.") from None
    if parsed_value < 0:
        raise ImproperlyConfigured(f"{name} no puede ser negativo.")
    return parsed_value


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
    "rest_framework.authtoken",
    "api",
    "corsheaders",
]

MIDDLEWARE = [
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
CORS_EXPOSE_HEADERS = ["X-Total-Count", "Retry-After"]

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
    "DEFAULT_THROTTLE_CLASSES": [
        "api.throttles.ReadThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "read": _env_rate("THROTTLE_READ_RATE", "120/min"),
        "ingest": _env_rate("THROTTLE_INGEST_RATE", "300/min"),
        "login": _env_rate("THROTTLE_LOGIN_RATE", "10/min"),
    },
    # Saltos de proxy delante de la app; sin valor, DRF toma todo X-Forwarded-For.
    "NUM_PROXIES": _env_non_negative_int("NUM_PROXIES"),
}

INGEST_API_KEY = os.getenv("INGEST_API_KEY", "")
NODE_OFFLINE_THRESHOLD_SECONDS = int(
    os.getenv("NODE_OFFLINE_THRESHOLD_SECONDS", "300")
)
ALERT_ON_WARNING = _env_bool("ALERT_ON_WARNING", False)
AUTO_REGISTER_NODES = _env_bool("AUTO_REGISTER_NODES", False)
# Con False, las consultas GET también exigen token (para cuando el frontend tenga login).
PUBLIC_READ_ACCESS = _env_bool("PUBLIC_READ_ACCESS", True)

# Servicio PyroGuard-IA (contrato v1.0). Sin URL, la IA queda deshabilitada y
# el riesgo se evalúa solo con las reglas del backend.
AI_SERVICE_URL = _env_service_url("AI_SERVICE_URL")
# Conexión corta para detectar rápido un servicio caído; lectura más amplia
# para dar tiempo a la inferencia.
AI_CONNECT_TIMEOUT = _env_positive_float("AI_CONNECT_TIMEOUT", 3.0)
AI_READ_TIMEOUT = _env_positive_float("AI_READ_TIMEOUT", 10.0)
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "{levelname} {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
