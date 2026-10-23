import logging

from django.db import transaction
from django.utils import timezone

from api.models import Node, RiskAssessment
from api.services.ai_client import AIPrediction, request_prediction
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

    # La IA se consulta con la lectura ya confirmada y fuera de cualquier
    # transacción, para no mantener bloqueos mientras dura el timeout.
    prediction = _predict(reading)

    try:
        with transaction.atomic():
            evaluation = evaluate_risk(
                {
                    "temperature": reading.temperature,
                    "humidity": reading.humidity,
                    "smoke": reading.smoke,
                    "flame": reading.flame,
                },
                ai_probability=prediction.probability,
            )
            reasons = evaluation["reasons"]
            if prediction.explanation:
                reasons = [*reasons, f"IA: {prediction.explanation}"]
            assessment = RiskAssessment.objects.create(
                reading=reading,
                risk_level=evaluation["level"],
                ai_probability=evaluation["ai_probability"],
                ai_model_version=prediction.model_version,
                ai_status=prediction.status,
                ai_risk_level=prediction.risk_level,
                ai_probabilities=prediction.probabilities,
                rule_reasons=reasons,
            )
            alert = maybe_create_alert(reading.node, reading, assessment)
        risk_level = assessment.risk_level
        alert_id = alert.pk if alert else None
    except Exception:
        logger.exception(
            "Falló el procesamiento posterior de la lectura id=%s; "
            "se conserva la lectura.",
            reading.pk,
        )

    logger.info(
        "Lectura recibida node_id=%s risk_level=%s ai_status=%s",
        reading.node.node_id,
        risk_level,
        prediction.status,
    )
    return reading, risk_level, alert_id


def _predict(reading):
    try:
        return request_prediction(reading)
    except Exception:
        # El cliente no debería lanzar excepciones; si ocurre, se sigue solo con reglas.
        logger.exception(
            "Falló inesperadamente la consulta a la IA para la lectura id=%s.",
            reading.pk,
        )
        return AIPrediction(status=RiskAssessment.AIStatus.UNAVAILABLE)
