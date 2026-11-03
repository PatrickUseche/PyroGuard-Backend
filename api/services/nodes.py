from django.conf import settings
from django.db.models import (
    Case,
    Count,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.shortcuts import get_object_or_404
from django.utils import timezone

from api.models import Alert, Node, RiskAssessment, SensorReading, connection_status_at
from api.serializers import SensorReadingSerializer
from api.services.dashboard_cache import dashboard_cache
from api.services.live_readings import live_readings
from api.services.node_status_cache import node_status_cache
from api.structures.priority_min_heap import PriorityMinHeap

RISK_PRIORITY = {"NORMAL": 1, "WARNING": 2, "FIRE": 3}


def nodes_with_current_risk():
    latest_assessment = (
        RiskAssessment.objects.filter(reading__node_id=OuterRef("pk"))
        .order_by("-created_at", "-pk")
        .values("risk_level")[:1]
    )
    return Node.objects.annotate(current_risk=Subquery(latest_assessment))


def _load_node_status(node_id):
    """Parte del estado que sale de la base de datos (es lo que se cachea)."""
    node = get_object_or_404(Node, node_id=node_id)
    latest_reading = (
        SensorReading.objects.filter(node=node)
        .select_related("node", "assessment")
        .order_by("-timestamp", "-pk")
        .first()
    )
    latest_assessment = (
        RiskAssessment.objects.filter(reading__node=node)
        .order_by("-created_at", "-pk")
        .first()
    )
    return {
        "node_id": node.node_id,
        "last_communication": node.last_communication,
        "latest_reading": (
            dict(SensorReadingSerializer(latest_reading).data)
            if latest_reading
            else None
        ),
        "current_risk": (
            latest_assessment.risk_level if latest_assessment else None
        ),
        "active_alerts_count": Alert.objects.filter(
            node=node,
            status__in=[Alert.Status.ACTIVE, Alert.Status.ACKNOWLEDGED],
        ).count(),
    }


def get_node_status(node_id):
    stored = node_status_cache.get(node_id)
    if stored is None:
        stored = _load_node_status(node_id)
        node_status_cache.put(node_id, stored)

    # Lo que depende del reloj o de la memoria se calcula en cada petición.
    connection_status = connection_status_at(stored["last_communication"])
    return {
        "node_id": stored["node_id"],
        "connection_status": connection_status,
        "last_communication": stored["last_communication"],
        "latest_reading": stored["latest_reading"],
        "current_risk": stored["current_risk"],
        "current_risk_stale": connection_status == "OFFLINE",
        "temperature_window": live_readings.temperature_window(node_id),
        "active_alerts_count": stored["active_alerts_count"],
    }


def get_dashboard_summary():
    summary = dashboard_cache.get()
    if summary is None:
        summary = _build_dashboard_summary()
        dashboard_cache.put(summary)
    return summary


def _build_dashboard_summary():
    now = timezone.now()
    offline_cutoff = now - timezone.timedelta(
        seconds=settings.NODE_OFFLINE_THRESHOLD_SECONDS
    )
    nodes = nodes_with_current_risk().annotate(
        latest_reading_id=Subquery(
            SensorReading.objects.filter(node_id=OuterRef("pk"))
            .order_by("-timestamp", "-pk")
            .values("pk")[:1]
        )
    )
    counts = nodes.aggregate(
        total_nodes=Count("pk"),
        nodes_online=Count(
            "pk",
            filter=Q(last_communication__gte=offline_cutoff),
        ),
        nodes_offline=Count(
            "pk",
            filter=Q(last_communication__lt=offline_cutoff),
        ),
        nodes_unknown=Count(
            "pk",
            filter=Q(last_communication__isnull=True),
        ),
        nodes_at_risk=Count(
            "pk",
            filter=Q(last_communication__gte=offline_cutoff)
            & Q(current_risk__in=["WARNING", "FIRE"]),
        ),
    )

    highest_risk = (
        nodes.filter(last_communication__gte=offline_cutoff)
        .aggregate(
            priority=Max(
                Case(
                    When(current_risk="FIRE", then=Value(3)),
                    When(current_risk="WARNING", then=Value(2)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
        )
        .get("priority")
    )
    overall_risk = next(
        (level for level, priority in RISK_PRIORITY.items() if priority == highest_risk),
        "NORMAL",
    )

    latest_reading_ids = list(nodes.values_list("latest_reading_id", flat=True))
    latest_readings = SensorReading.objects.filter(
        pk__in=[reading_id for reading_id in latest_reading_ids if reading_id]
    ).select_related("node", "assessment").order_by("node__node_id")

    counts.update(
        active_alerts=Alert.objects.filter(
            status__in=[Alert.Status.ACTIVE, Alert.Status.ACKNOWLEDGED]
        ).count(),
        overall_risk=overall_risk,
        latest_readings=list(SensorReadingSerializer(latest_readings, many=True).data),
    )
    return counts


def _risk_priority(row):
    """Prioridad de un nodo: más riesgo, luego más probabilidad de la IA, luego el id."""
    return (-RISK_PRIORITY[row["current_risk"]], -(row["ai_probability"] or 0.0), row["node_id"])


def get_top_risk_nodes(k):
    """Los ``k`` nodos de mayor riesgo actual, del más al menos peligroso.

    Se arma un montículo con todos los nodos que tienen una evaluación y se
    extraen solo ``k``: O(n + k log n), sin ordenar la lista completa. Un nodo
    desconectado conserva su último riesgo conocido y lo indica con
    ``current_risk_stale``.
    """
    latest_probability = (
        RiskAssessment.objects.filter(reading__node_id=OuterRef("pk"))
        .order_by("-created_at", "-pk")
        .values("ai_probability")[:1]
    )
    nodes = (
        nodes_with_current_risk()
        .filter(current_risk__isnull=False)
        .annotate(ai_probability=Subquery(latest_probability))
    )
    rows = [
        {
            "node_id": node.node_id,
            "name": node.name,
            "current_risk": node.current_risk,
            "ai_probability": node.ai_probability,
            "connection_status": node.connection_status,
            "current_risk_stale": node.connection_status == "OFFLINE",
            "last_communication": node.last_communication,
        }
        for node in nodes
    ]
    return PriorityMinHeap.smallest(rows, k, priority=_risk_priority)
