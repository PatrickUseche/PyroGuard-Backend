import logging

from django.db import transaction
from django.utils import timezone

from api.models import Node, RiskAssessment
from api.services.alerts import maybe_create_alert
from api.services.risk_rules import evaluate_risk


logger = logging.getLogger("api.readings")


def ingest_reading(serializer):
    risk_level = None
    alert_id = None

    with transaction.atomic():
        reading = serializer.save()
        communicated_at = timezone.now()
        try:
            with transaction.atomic():
                Node.objects.filter(pk=reading.node_id).update(
                    last_communication=communicated_at,
                )
                reading.node.last_communication = communicated_at
        except Exception:
            logger.exception(
                "Falló la actualización de comunicación del nodo para la lectura "
                "id=%s; se conserva la lectura.",
                reading.pk,
            )

        try:
            with transaction.atomic():
                ai_probability = None
                # TODO(IA): reemplazar por la llamada al servicio de predicción
                evaluation = evaluate_risk(
                    {
                        "temperature": reading.temperature,
                        "humidity": reading.humidity,
                        "smoke": reading.smoke,
                        "flame": reading.flame,
                    },
                    ai_probability=ai_probability,
                )
                risk_level = evaluation["level"]
                assessment = RiskAssessment.objects.create(
                    reading=reading,
                    risk_level=risk_level,
                    ai_probability=evaluation["ai_probability"],
                    rule_reasons=evaluation["reasons"],
                )
                alert = maybe_create_alert(reading.node, reading, assessment)
                alert_id = alert.pk if alert else None
        except Exception:
            logger.exception(
                "Falló el procesamiento posterior de la lectura id=%s; "
                "se conserva la lectura.",
                reading.pk,
            )

    logger.info(
        "Lectura recibida node_id=%s risk_level=%s",
        reading.node.node_id,
        risk_level,
    )
    return reading, risk_level, alert_id