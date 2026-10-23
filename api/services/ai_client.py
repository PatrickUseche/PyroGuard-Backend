"""Cliente HTTP de PyroGuard-IA según el contrato IA-Backend v1.0.

El cliente nunca propaga excepciones: cualquier fallo se traduce en un
ai_status distinto de OK para que la ingesta continúe solo con las reglas.
"""
import logging
import math
from dataclasses import dataclass, field

import requests
from django.conf import settings

from api.models import RiskAssessment, SensorReading


logger = logging.getLogger("api.ai")

AIStatus = RiskAssessment.AIStatus
SUPPORTED_CONTRACT_MAJOR = "1"
RISK_LEVELS = set(RiskAssessment.RiskLevel.values)
MODEL_VERSION_MAX_LENGTH = RiskAssessment._meta.get_field("ai_model_version").max_length


class InvalidPredictionError(ValueError):
    pass


@dataclass(frozen=True)
class AIPrediction:
    status: str
    risk_level: str = ""
    probability: float | None = None
    probabilities: dict = field(default_factory=dict)
    model_version: str = ""
    explanation: str = ""

    @property
    def ok(self):
        return self.status == AIStatus.OK


def build_payload(reading: SensorReading) -> dict:
    return {
        "node_id": reading.node.node_id,
        "temperature": reading.temperature,
        "humidity": reading.humidity,
        "smoke": reading.smoke,
        "gas": reading.gas,
        "flame": reading.flame,
        "timestamp": reading.timestamp.isoformat(),
    }


def request_prediction(reading: SensorReading) -> AIPrediction:
    """Solicita la predicción de una lectura ya guardada."""
    if not settings.AI_SERVICE_URL:
        return AIPrediction(status=AIStatus.DISABLED)

    headers = {}
    if settings.AI_API_KEY:
        headers["X-AI-API-Key"] = settings.AI_API_KEY

    try:
        response = requests.post(
            f"{settings.AI_SERVICE_URL}/predict",
            json=build_payload(reading),
            headers=headers,
            timeout=(settings.AI_CONNECT_TIMEOUT, settings.AI_READ_TIMEOUT),
        )
    except requests.RequestException as error:
        logger.warning(
            "Servicio de IA no disponible para la lectura id=%s: %s",
            reading.pk,
            type(error).__name__,
        )
        return AIPrediction(status=AIStatus.UNAVAILABLE)

    if response.status_code != 200:
        return _error_prediction(reading, response)

    try:
        return _parse_prediction(response.json())
    except (ValueError, InvalidPredictionError) as error:
        logger.warning(
            "Respuesta de IA fuera de contrato para la lectura id=%s: %s",
            reading.pk,
            error,
        )
        return AIPrediction(status=AIStatus.INVALID_RESPONSE)


def _error_prediction(reading, response) -> AIPrediction:
    status_code = response.status_code
    try:
        error_code = response.json().get("code", "")
    except (ValueError, AttributeError):
        error_code = ""

    if status_code in (401, 403):
        logger.error(
            "La IA rechazó la credencial (HTTP %s); revisar AI_API_KEY.",
            status_code,
        )
        return AIPrediction(status=AIStatus.REJECTED)
    if 400 <= status_code < 500:
        logger.warning(
            "La IA rechazó la lectura id=%s (HTTP %s %s).",
            reading.pk,
            status_code,
            error_code,
        )
        return AIPrediction(status=AIStatus.REJECTED)
    if status_code >= 500:
        logger.warning(
            "Error del servicio de IA para la lectura id=%s (HTTP %s %s).",
            reading.pk,
            status_code,
            error_code,
        )
        return AIPrediction(status=AIStatus.UNAVAILABLE)

    logger.warning("Código HTTP inesperado de la IA: %s.", status_code)
    return AIPrediction(status=AIStatus.INVALID_RESPONSE)


def _is_probability(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def _parse_prediction(body) -> AIPrediction:
    if not isinstance(body, dict):
        raise InvalidPredictionError("el cuerpo no es un objeto JSON")

    contract_version = body.get("contract_version")
    if (
        not isinstance(contract_version, str)
        or contract_version.split(".")[0] != SUPPORTED_CONTRACT_MAJOR
    ):
        raise InvalidPredictionError(
            f"contract_version no soportada: {contract_version!r}"
        )

    risk_level = body.get("risk_level")
    if risk_level not in RISK_LEVELS:
        raise InvalidPredictionError(f"risk_level inválido: {risk_level!r}")

    probability = body.get("risk_probability")
    if not _is_probability(probability):
        raise InvalidPredictionError("risk_probability debe estar entre 0 y 1")

    probabilities = body.get("probabilities")
    if (
        not isinstance(probabilities, dict)
        or not set(probabilities) <= RISK_LEVELS
        or not all(_is_probability(value) for value in probabilities.values())
    ):
        raise InvalidPredictionError("probabilities no cumple el contrato")

    model_version = body.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise InvalidPredictionError("model_version es obligatorio")

    safety_rules = body.get("safety_rules")
    explanation = ""
    if isinstance(safety_rules, dict) and isinstance(safety_rules.get("explanation"), str):
        explanation = safety_rules["explanation"]

    return AIPrediction(
        status=AIStatus.OK,
        risk_level=risk_level,
        probability=float(probability),
        probabilities={level: float(value) for level, value in probabilities.items()},
        model_version=model_version[:MODEL_VERSION_MAX_LENGTH],
        explanation=explanation,
    )
