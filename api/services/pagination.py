import logging

from rest_framework.exceptions import ParseError


logger = logging.getLogger("api.readings")

MAX_LIMIT = 500
TOTAL_COUNT_HEADER = "X-Total-Count"


def _parse_integer(value, name, default):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ParseError(f"'{name}' debe ser un número entero.") from None


def parse_pagination(query_params, default_limit):
    """Devuelve (limit, offset) validados a partir de los parámetros de la URL."""
    try:
        limit = _parse_integer(query_params.get("limit"), "limit", default_limit)
        if not 1 <= limit <= MAX_LIMIT:
            raise ParseError(f"'limit' debe estar entre 1 y {MAX_LIMIT}.")

        offset = _parse_integer(query_params.get("offset"), "offset", 0)
        if offset < 0:
            raise ParseError("'offset' debe ser mayor o igual que 0.")
    except ParseError as error:
        logger.warning("Paginación rechazada: %s", error.detail)
        raise
    return limit, offset


def paginate(queryset, query_params, default_limit):
    """Devuelve (página, total) del queryset según `limit` y `offset`."""
    limit, offset = parse_pagination(query_params, default_limit)
    return queryset[offset:offset + limit], queryset.count()
