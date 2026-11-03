import logging

from django.db import transaction
from django.utils import timezone

from api.models import Node, RiskAssessment
from api.services.ai_client import AIPrediction, request_prediction
from api.services.alerts import maybe_create_alert
from api.services.dashboard_cache import dashboard_cache
from api.services.duplicate_readings import duplicate_readings
from api.services.live_readings import live_readings
from api.services.neighbor_warnings import warn_neighbors_of_fire
from api.services.node_status_cache import node_status_cache
from api.services.risk_rules import evaluate_risk


logger = logging.getLogger("api.readings")


class DuplicateReadingError(Exception):
    """La lectura ya estaba registrada (mismo nodo y mismo ``timestamp``)."""

    def __init__(self, reading):
        super().__init__("La lectura ya estaba registrada.")
        self.reading = reading


def ingest_reading(serializer):
    risk_level = None
    alert_id = None

    node_id = serializer.validated_data["node_id"]
    timestamp = serializer.validated_data["timestamp"]
    existing = duplicate_readings.find(node_id, timestamp)
    if existing is not None:
        logger.info("Lectura duplicada descartada node_id=%s", node_id)
        raise DuplicateReadingError(existing)

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

    duplicate_readings.remember(node_id, timestamp)

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

    # Algunas escrituras (como el ``update`` de la última comunicación) no emiten
    # señales, así que al terminar se descarta el estado cacheado del nodo.
    node_status_cache.invalidate(reading.node.node_id)
    dashboard_cache.invalidate()

    if risk_level == RiskAssessment.RiskLevel.FIRE:
        try:
            warn_neighbors_of_fire(node_id)
        except Exception:
            logger.exception(
                "No se pudo avisar a los vecinos del nodo %s; se conserva la lectura.",
                node_id,
            )

    try:
        live_readings.record(reading)
    except Exception:
        logger.exception(
            "No se pudo guardar la lectura id=%s en el buffer reciente; "
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
