"""Cola de lecturas pendientes de evaluación por la IA.

Con ``AI_ASYNC_EVALUATION=True`` la ingesta no espera a PyroGuard-IA: guarda la
lectura con el riesgo de las reglas y marca su evaluación como ``PENDING``. Esas
evaluaciones pendientes son la cola, y se atienden por orden de llegada (FIFO) con
``manage.py drain_ai_queue``.

La cola vive en la base (el estado ``PENDING``), no en memoria, porque quien la
vacía es un comando que corre en otro proceso. ``FirstInFirstOutQueue`` es el lote
de trabajo en memoria de cada ejecución: se llena con los pendientes más antiguos y
se vacía de uno en uno.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from api.models import RiskAssessment, SensorReading
from api.services.ai_client import AIPrediction
from api.services.alerts import maybe_create_alert
from api.services.ingestion import _predict
from api.services.neighbor_warnings import warn_neighbors_of_fire
from api.services.risk_rules import evaluate_risk
from api.structures.first_in_first_out_queue import FirstInFirstOutQueue

logger = logging.getLogger("api.readings")

PENDING = RiskAssessment.AIStatus.PENDING


def pending_count():
    return RiskAssessment.objects.filter(ai_status=PENDING).count()


def load_batch(limit):
    """Cola FIFO con los ids de las ``limit`` evaluaciones pendientes más antiguas."""
    ids = (
        RiskAssessment.objects.filter(ai_status=PENDING)
        .order_by("created_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    return FirstInFirstOutQueue(ids)


@dataclass
class DrainResult:
    evaluated: int = 0
    skipped: int = 0
    deferred: int = 0
    stopped_early: bool = False


def evaluate_pending(assessment_id):
    """Consulta a la IA una evaluación pendiente y la completa.

    Devuelve ``"evaluated"`` si quedó resuelta, ``"skipped"`` si otro proceso ya la
    había atendido y ``"deferred"`` si la IA no respondió (queda pendiente).
    """
    with transaction.atomic():
        assessment = (
            RiskAssessment.objects.select_for_update()
            .select_related("reading__node")
            .filter(pk=assessment_id, ai_status=PENDING)
            .first()
        )
        if assessment is None:
            return "skipped"

        reading = assessment.reading
        prediction = _predict(reading)
        if prediction.status == RiskAssessment.AIStatus.UNAVAILABLE:
            return "deferred"

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
        assessment.risk_level = evaluation["level"]
        assessment.ai_probability = evaluation["ai_probability"]
        assessment.ai_model_version = prediction.model_version
        assessment.ai_status = prediction.status
        assessment.ai_risk_level = prediction.risk_level
        assessment.ai_probabilities = prediction.probabilities
        assessment.rule_reasons = reasons
        assessment.save()
        maybe_create_alert(reading.node, reading, assessment)

    if assessment.risk_level == RiskAssessment.RiskLevel.FIRE:
        try:
            warn_neighbors_of_fire(reading.node.node_id)
        except Exception:
            logger.exception("No se pudo avisar a los vecinos del nodo %s.", reading.node.node_id)
    return "evaluated"


def drain(limit=500):
    """Atiende hasta ``limit`` evaluaciones pendientes, de la más antigua a la más nueva.

    Si la IA no responde, se detiene en la primera para no esperar un timeout por
    cada lectura pendiente; las que quedan seguirán pendientes para la próxima vez.
    """
    queue = load_batch(limit)
    result = DrainResult()
    while not queue.is_empty():
        outcome = evaluate_pending(queue.dequeue())
        if outcome == "evaluated":
            result.evaluated += 1
        elif outcome == "skipped":
            result.skipped += 1
        else:
            result.deferred += 1
            result.stopped_early = True
            break
    return result


UNASSESSED_MIN_AGE = timedelta(seconds=30)


def unassessed_count():
    return SensorReading.objects.filter(assessment__isnull=True).count()


def repair_unassessed(limit=500):
    """Evalúa las lecturas que se guardaron pero se quedaron sin ``RiskAssessment``.

    La ingesta confirma la lectura antes de evaluarla; si la evaluación o la alerta
    fallan, la lectura se conserva pero sin riesgo ni alerta, y nada más la vuelve a
    mirar. Aquí se recuperan, de la más antigua a la más nueva. Se ignoran las
    lecturas de los últimos segundos para no pisar una ingesta que todavía está en
    curso. Devuelve cuántas se repararon.
    """
    cutoff = timezone.now() - UNASSESSED_MIN_AGE
    ids = list(
        SensorReading.objects.filter(assessment__isnull=True, timestamp__lt=cutoff)
        .order_by("timestamp", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    repaired = 0
    for reading_id in ids:
        try:
            if _assess_unassessed(reading_id):
                repaired += 1
        except IntegrityError:
            # Otro proceso evaluó la lectura entre la consulta y la creación.
            continue
        except Exception:
            logger.exception("No se pudo reparar la lectura id=%s.", reading_id)
    return repaired


def _assess_unassessed(reading_id):
    with transaction.atomic():
        reading = (
            SensorReading.objects.select_for_update()
            .select_related("node")
            .filter(pk=reading_id, assessment__isnull=True)
            .first()
        )
        if reading is None:
            return False

        if settings.AI_ASYNC_EVALUATION and settings.AI_SERVICE_URL:
            prediction = AIPrediction(status=PENDING)
        else:
            prediction = _predict(reading)
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
        maybe_create_alert(reading.node, reading, assessment)

    if assessment.risk_level == RiskAssessment.RiskLevel.FIRE:
        try:
            warn_neighbors_of_fire(reading.node.node_id)
        except Exception:
            logger.exception("No se pudo avisar a los vecinos del nodo %s.", reading.node.node_id)
    logger.info("Lectura reparada id=%s risk_level=%s", reading.pk, assessment.risk_level)
    return True
