"""Serializers de solo documentación para el esquema OpenAPI.

Las vistas devuelven diccionarios armados a mano; estos serializers no se usan para
validar ni para responder, solo describen su forma (y sus ejemplos) en ``/api/schema/``.
"""
from drf_spectacular.utils import OpenApiExample, OpenApiParameter
from rest_framework import serializers

from .serializers import AlertSerializer, SensorReadingSerializer

RISK_LEVELS = ["NORMAL", "WARNING", "FIRE"]
CONNECTION_STATES = ["ONLINE", "OFFLINE", "UNKNOWN"]
AT_RISK_LEVELS = ["WARNING", "FIRE"]


# --- Parámetros reutilizables -------------------------------------------------------

LIMIT = OpenApiParameter("limit", int, description="Máximo de elementos a devolver.")
OFFSET = OpenApiParameter("offset", int, description="Elementos que se saltan desde el inicio.")
FROM = OpenApiParameter("from", str, description="Inicio del intervalo (ISO 8601, incluido).")
TO = OpenApiParameter("to", str, description="Fin del intervalo (ISO 8601, incluido).")
RANGE = OpenApiParameter("range", str, enum=["24h", "7d"], description="Atajo: últimas 24 horas o 7 días.")
ORDER = OpenApiParameter("order", str, enum=["asc", "desc"], description="Orden por fecha; por defecto `desc`.")

TOTAL_COUNT_HEADER = OpenApiParameter(
    "X-Total-Count", int, OpenApiParameter.HEADER,
    description="Total de elementos sin paginar.", response=True,
)


# --- Estado, resumen y riesgo -------------------------------------------------------

class TemperatureWindowSerializer(serializers.Serializer):
    size = serializers.IntegerField(help_text="Capacidad de la ventana (`TEMPERATURE_WINDOW_SIZE`).")
    readings = serializers.IntegerField(help_text="Lecturas que contiene ahora.")
    max = serializers.FloatField(help_text="Temperatura máxima de la ventana.")
    min = serializers.FloatField(help_text="Temperatura mínima de la ventana.")


class NodeStatusSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    connection_status = serializers.ChoiceField(CONNECTION_STATES)
    last_communication = serializers.DateTimeField(allow_null=True)
    latest_reading = SensorReadingSerializer(allow_null=True)
    current_risk = serializers.ChoiceField(RISK_LEVELS, allow_null=True)
    current_risk_stale = serializers.BooleanField(
        help_text="`true` si el nodo está OFFLINE: el riesgo es el último conocido, no uno actual."
    )
    temperature_window = TemperatureWindowSerializer(allow_null=True)
    active_alerts_count = serializers.IntegerField()


class DashboardSummarySerializer(serializers.Serializer):
    total_nodes = serializers.IntegerField()
    nodes_online = serializers.IntegerField()
    nodes_offline = serializers.IntegerField()
    nodes_unknown = serializers.IntegerField()
    nodes_at_risk = serializers.IntegerField(help_text="Nodos online en WARNING o FIRE.")
    active_alerts = serializers.IntegerField()
    overall_risk = serializers.ChoiceField(RISK_LEVELS)
    latest_readings = SensorReadingSerializer(many=True)


class TopRiskNodeSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    current_risk = serializers.ChoiceField(RISK_LEVELS)
    ai_probability = serializers.FloatField(allow_null=True)
    connection_status = serializers.ChoiceField(CONNECTION_STATES)
    current_risk_stale = serializers.BooleanField()
    last_communication = serializers.DateTimeField(allow_null=True)


class ZoneNodeSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    current_risk = serializers.ChoiceField(AT_RISK_LEVELS)


class RiskZoneSerializer(serializers.Serializer):
    zone_id = serializers.CharField(help_text="Primer `node_id` (alfabético) de la zona.")
    risk_level = serializers.ChoiceField(AT_RISK_LEVELS, help_text="Nivel más alto de la zona.")
    size = serializers.IntegerField()
    nodes = ZoneNodeSerializer(many=True)


# --- Vecinos y búsqueda -------------------------------------------------------------

class NodeLinksSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    neighbors = serializers.ListField(child=serializers.CharField(), help_text="Vecinos directos, en orden alfabético.")


class NodeLinkRequestSerializer(serializers.Serializer):
    neighbor = serializers.CharField(help_text="`node_id` del nodo vecino.")


class NodeLinkCreatedSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    neighbor = serializers.CharField()


class NeighborSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    hops = serializers.IntegerField(help_text="Saltos mínimos desde el nodo consultado.")


class NodeNeighborsSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    hops = serializers.IntegerField()
    neighbors = NeighborSerializer(many=True)


class NodeSearchSerializer(serializers.Serializer):
    prefix = serializers.CharField()
    results = serializers.ListField(child=serializers.CharField())


# --- Serie histórica ----------------------------------------------------------------

class SeriesPointSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    value = serializers.FloatField()


class SeriesBucketSerializer(serializers.Serializer):
    start = serializers.DateTimeField(help_text="Inicio del tramo, alineado al reloj (UTC).")
    count = serializers.IntegerField()
    average = serializers.FloatField()


class SeriesEntrySerializer(serializers.Serializer):
    node_id = serializers.CharField()
    count = serializers.IntegerField(help_text="Lecturas con el campo pedido dentro del intervalo.")
    average = serializers.FloatField(allow_null=True)
    points = SeriesPointSerializer(many=True, required=False, help_text="Sin `step`.")
    buckets = SeriesBucketSerializer(many=True, required=False, help_text="Con `step`.")


class SeriesResponseSerializer(serializers.Serializer):
    field = serializers.CharField()
    # `from` es palabra reservada de Python: se declara con su nombre real.
    to = serializers.DateTimeField()
    step = serializers.IntegerField(allow_null=True)
    series = SeriesEntrySerializer(many=True)
    merged = serializers.ListField(
        child=serializers.DictField(), required=False,
        help_text="Con `merge=true`: todos los nodos en una sola línea de tiempo.",
    )


SeriesResponseSerializer._declared_fields["from"] = serializers.DateTimeField()


# --- Ingesta y salud ----------------------------------------------------------------

class IngestResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(["success", "duplicate"])
    message = serializers.CharField()
    reading = SensorReadingSerializer()
    risk_level = serializers.ChoiceField(RISK_LEVELS, allow_null=True)
    alert_id = serializers.IntegerField(allow_null=True)


class ErrorSerializer(serializers.Serializer):
    status = serializers.CharField(default="error")
    errors = serializers.DictField(required=False)
    message = serializers.CharField(required=False)


class HealthComponentSerializer(serializers.Serializer):
    status = serializers.CharField()
    latency_ms = serializers.FloatField(required=False)


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(["ok", "degraded", "down"])
    database = HealthComponentSerializer()
    ai = HealthComponentSerializer(required=False)


# --- Ejemplos -----------------------------------------------------------------------

READING_EXAMPLE = {
    "node_id": "SIM-001",
    "temperature": 24.5,
    "humidity": 48,
    "smoke": 18,
    "gas": 3.2,
    "flame": False,
    "timestamp": "2026-10-30T15:30:00Z",
}

EXAMPLE_INGEST_REQUEST = OpenApiExample("Lectura normal", value=READING_EXAMPLE, request_only=True)
EXAMPLE_FIRE_REQUEST = OpenApiExample(
    "Lectura con llama",
    value={**READING_EXAMPLE, "temperature": 78.2, "humidity": 12, "smoke": 640, "flame": True},
    request_only=True,
)
EXAMPLE_NODE_STATUS = OpenApiExample(
    "Nodo en línea y normal",
    value={
        "node_id": "SIM-001",
        "connection_status": "ONLINE",
        "last_communication": "2026-10-30T15:30:01Z",
        "latest_reading": {**READING_EXAMPLE, "risk_level": "NORMAL", "ai": None},
        "current_risk": "NORMAL",
        "current_risk_stale": False,
        "temperature_window": {"size": 20, "readings": 20, "max": 25.1, "min": 23.9},
        "active_alerts_count": 0,
    },
    response_only=True,
)
EXAMPLE_HEALTH_DEGRADED = OpenApiExample(
    "IA caída",
    value={"status": "degraded", "database": {"status": "ok", "latency_ms": 1.4}, "ai": {"status": "unavailable"}},
    response_only=True,
)
EXAMPLE_SERIES = OpenApiExample(
    "Promedios cada 5 minutos",
    value={
        "field": "temperature",
        "from": "2026-10-30T12:00:00Z",
        "to": "2026-10-30T13:00:00Z",
        "step": 300,
        "series": [
            {
                "node_id": "SIM-001",
                "count": 12,
                "average": 24.1,
                "buckets": [{"start": "2026-10-30T12:00:00Z", "count": 4, "average": 23.8}],
            }
        ],
    },
    response_only=True,
)
EXAMPLE_ZONES = OpenApiExample(
    "Una zona con dos nodos",
    value=[
        {
            "zone_id": "SIM-001",
            "risk_level": "FIRE",
            "size": 2,
            "nodes": [
                {"node_id": "SIM-001", "current_risk": "FIRE"},
                {"node_id": "SIM-002", "current_risk": "WARNING"},
            ],
        }
    ],
    response_only=True,
)

__all__ = [name for name in dir() if not name.startswith("_")] + ["AlertSerializer"]
