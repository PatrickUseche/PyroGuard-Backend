from datetime import timedelta
import logging

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ParseError


logger = logging.getLogger("api.readings")


def parse_datetime_parameter(value, parameter_name):
    try:
        parsed_value = parse_datetime(value)
    except ValueError:
        parsed_value = None
    if parsed_value is None:
        raise ParseError(
            f"El parámetro '{parameter_name}' debe tener formato ISO 8601."
        )
    if timezone.is_naive(parsed_value):
        parsed_value = timezone.make_aware(parsed_value)
    return parsed_value


def filter_readings(readings, query_params):
    from_value = query_params.get("from")
    to_value = query_params.get("to")
    try:
        from_date = (
            parse_datetime_parameter(from_value, "from") if from_value else None
        )
        to_date = parse_datetime_parameter(to_value, "to") if to_value else None
        if from_date and to_date and from_date > to_date:
            raise ParseError("El parámetro 'from' no puede ser posterior a 'to'.")
        if from_date:
            readings = readings.filter(timestamp__gte=from_date)
        if to_date:
            readings = readings.filter(timestamp__lte=to_date)

        range_value = query_params.get("range")
        range_durations = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
        }
        if range_value:
            if range_value not in range_durations:
                raise ParseError("'range' debe ser '24h' o '7d'.")
            readings = readings.filter(
                timestamp__gte=timezone.now() - range_durations[range_value]
            )
    except ParseError as error:
        logger.warning("Consulta de lecturas rechazada: %s", error.detail)
        raise

    order = query_params.get("order", "desc")
    if order not in {"asc", "desc"}:
        logger.warning("Consulta de lecturas rechazada: orden inválido.")
        raise ParseError("'order' debe ser 'asc' o 'desc'.")

    timestamp_order = "timestamp" if order == "asc" else "-timestamp"
    return readings.order_by(timestamp_order, "pk")