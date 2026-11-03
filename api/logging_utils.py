"""Formato JSON de los logs y contexto de la petición (``request_id``)."""
import contextvars
import json
import logging
from datetime import datetime, timezone

#: Identificador de la petición en curso; "-" fuera de una petición.
request_id_var = contextvars.ContextVar("request_id", default="-")

# Atributos que ``logging.LogRecord`` ya trae y no son datos extra del mensaje.
_STANDARD_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "request_id", "taskName"}


class RequestIdFilter(logging.Filter):
    """Añade ``record.request_id`` a cada registro."""

    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Un objeto JSON por línea: fácil de buscar en Render, Loki o cualquier agregador."""

    def format(self, record):
        entry = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRIBUTES and not key.startswith("_"):
                entry[key] = value
        return json.dumps(entry, ensure_ascii=False, default=str)
