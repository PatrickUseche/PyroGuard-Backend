"""Lectura y validación de los parámetros de ``GET /readings/series/``."""
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ParseError

from api.models import Node, SensorReading
from api.services.reading_queries import parse_datetime_parameter
from api.services.series import MAX_BUCKETS, TimeSeries

FIELDS = ("temperature", "humidity", "smoke", "gas")
MAX_NODES = 10
MAX_POINTS = 5000
MAX_ROWS_FOR_BUCKETS = 200000
MAX_SPAN = timedelta(days=31)
DEFAULT_SPAN = timedelta(hours=24)
MAX_STEP_SECONDS = 86400


class SeriesQuery:
    def __init__(self, node_ids, field, start, end, step, merge):
        self.node_ids = node_ids
        self.field = field
        self.start = start
        self.end = end
        self.step = step
        self.merge = merge


def _parse_bool(value, name):
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no", ""}:
        return False
    raise ParseError(f"'{name}' debe ser true o false.")


def parse_series_query(query_params):
    raw_nodes = [
        part.strip()
        for value in query_params.getlist("node_id")
        for part in value.split(",")
        if part.strip()
    ]
    node_ids = list(dict.fromkeys(raw_nodes))
    if not node_ids:
        raise ParseError("Indica al menos un 'node_id'.")
    if len(node_ids) > MAX_NODES:
        raise ParseError(f"Se pueden pedir hasta {MAX_NODES} nodos a la vez.")

    field = query_params.get("field", "temperature")
    if field not in FIELDS:
        raise ParseError(f"'field' debe ser uno de: {', '.join(FIELDS)}.")

    from_value = query_params.get("from")
    to_value = query_params.get("to")
    end = parse_datetime_parameter(to_value, "to") if to_value else timezone.now()
    start = parse_datetime_parameter(from_value, "from") if from_value else end - DEFAULT_SPAN
    if start > end:
        raise ParseError("El parámetro 'from' no puede ser posterior a 'to'.")
    if end - start > MAX_SPAN:
        raise ParseError(f"El intervalo no puede superar {MAX_SPAN.days} días.")

    step = None
    raw_step = query_params.get("step")
    if raw_step is not None:
        try:
            step = int(raw_step)
        except ValueError:
            raise ParseError("'step' debe ser un número entero de segundos.") from None
        if not 1 <= step <= MAX_STEP_SECONDS:
            raise ParseError(f"'step' debe estar entre 1 y {MAX_STEP_SECONDS} segundos.")
        if (end - start) / timedelta(seconds=step) > MAX_BUCKETS:
            raise ParseError(
                f"Con ese intervalo y 'step' saldrían más de {MAX_BUCKETS} tramos; sube 'step'."
            )

    return SeriesQuery(node_ids, field, start, end, step, _parse_bool(query_params.get("merge"), "merge"))


def load_series(query, node_id):
    """Carga de la base la serie de un nodo en el intervalo pedido."""
    get_object_or_404(Node, node_id=node_id)
    row_limit = MAX_POINTS if query.step is None else MAX_ROWS_FOR_BUCKETS
    rows = list(
        SensorReading.objects.filter(
            node__node_id=node_id,
            timestamp__gte=query.start,
            timestamp__lte=query.end,
        )
        .exclude(**{f"{query.field}__isnull": True})
        .order_by("timestamp", "pk")
        .values_list("timestamp", query.field)[: row_limit + 1]
    )
    if len(rows) > row_limit:
        hint = "acorta el intervalo o usa 'step'" if query.step is None else "acorta el intervalo"
        raise ParseError(f"El nodo '{node_id}' tiene más de {row_limit} lecturas en ese intervalo; {hint}.")
    return TimeSeries(rows)
