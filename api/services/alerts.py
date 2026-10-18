from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from api.models import Alert, Node, RiskAssessment, SensorReading


def maybe_create_alert(
    node: Node,
    reading: SensorReading,
    assessment: RiskAssessment,
) -> Alert | None:
    """Crea o actualiza una alerta persistente según el nivel evaluado."""
    level = assessment.risk_level
    if level == RiskAssessment.RiskLevel.WARNING and not settings.ALERT_ON_WARNING:
        return None
    if level not in {RiskAssessment.RiskLevel.WARNING, RiskAssessment.RiskLevel.FIRE}:
        return None

    level_label = {
        RiskAssessment.RiskLevel.WARNING: "advertencia",
        RiskAssessment.RiskLevel.FIRE: "incendio",
    }[level]
    message_reasons = "; ".join(assessment.rule_reasons) or "sin razones adicionales"
    message = (
        f"Alerta de {level_label} (nivel {level}) en el nodo {node.node_id}. "
        f"Razones: {message_reasons}"
    )
    now = timezone.now()

    with transaction.atomic():
        Node.objects.select_for_update().get(pk=node.pk)
        existing_alert = (
            Alert.objects.select_for_update()
            .filter(
                node=node,
                level=level,
                status__in=[Alert.Status.ACTIVE, Alert.Status.ACKNOWLEDGED],
            )
            .order_by("-created_at")
            .first()
        )
        if existing_alert:
            Alert.objects.filter(pk=existing_alert.pk).update(
                occurrences=F("occurrences") + 1,
                last_seen_at=now,
            )
            existing_alert.refresh_from_db()
            return existing_alert

        return Alert.objects.create(
            node=node,
            reading=reading,
            assessment=assessment,
            level=level,
            probability=assessment.ai_probability,
            message=message,
            last_seen_at=now,
        )