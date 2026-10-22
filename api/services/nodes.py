from django.conf import settings
from django.db.models import (
    Case,
    Count,
    F,
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

from api.models import Alert, Node, RiskAssessment, SensorReading
from api.serializers import SensorReadingSerializer


RISK_PRIORITY = {"NORMAL": 1, "WARNING": 2, "FIRE": 3}


def nodes_with_current_risk():
    latest_assessment = (
        RiskAssessment.objects.filter(reading__node_id=OuterRef("pk"))
        .order_by("-created_at", "-pk")
        .values("risk_level")[:1]
    )
    return Node.objects.annotate(current_risk=Subquery(latest_assessment))


def get_node_status(node_id):
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
    connection_status = node.connection_status
    return {
        "node_id": node.node_id,
        "connection_status": connection_status,
        "last_communication": node.last_communication,
        "latest_reading": (
            SensorReadingSerializer(latest_reading).data
            if latest_reading
            else None
        ),
        "current_risk": (
            latest_assessment.risk_level if latest_assessment else None
        ),
        "current_risk_stale": connection_status == "OFFLINE",
        "active_alerts_count": Alert.objects.filter(
            node=node,
            status__in=[Alert.Status.ACTIVE, Alert.Status.ACKNOWLEDGED],
        ).count(),
    }


def get_dashboard_summary():
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
        latest_readings=SensorReadingSerializer(latest_readings, many=True).data,
    )
    return counts