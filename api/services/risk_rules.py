"""Clasificación determinista del riesgo mediante reglas del prototipo.

NORMAL indica que no se detectaron señales, WARNING indica una o más señales
sin alcanzar emergencia y FIRE requiere dos señales fuertes. Los umbrales son
SMOKE_WARNING=40, SMOKE_FIRE=60, TEMP_WARNING=40, TEMP_FIRE=50 y
HUMIDITY_DRY=25. La llama, humo >= 60 y temperatura >= 50 son señales fuertes;
humo >= 40, temperatura >= 40 y humedad <= 25 con temperatura >= 35 también
son señales. La probabilidad de IA puede elevar el nivel, pero nunca reducirlo.
"""

# umbrales del prototipo, ajustables por el equipo.
SMOKE_WARNING = 40
SMOKE_FIRE = 60
TEMP_WARNING = 40
TEMP_FIRE = 50
HUMIDITY_DRY = 25


def evaluate_risk(reading_data, ai_probability: float | None = None) -> dict:
    """Devuelve el nivel, las razones y la probabilidad recibida de IA."""
    flame = bool(reading_data.get("flame", False))
    smoke = float(reading_data.get("smoke", 0) or 0)
    temperature = float(reading_data.get("temperature", 0) or 0)
    humidity = float(reading_data.get("humidity", 100) or 0)

    reasons = []
    strong_signals = []

    if flame:
        reasons.append("Se detectó llama.")
        strong_signals.append("flame")
    if smoke >= SMOKE_WARNING:
        reasons.append("El nivel de humo alcanzó el umbral de advertencia.")
        if smoke >= SMOKE_FIRE:
            strong_signals.append("smoke")
    if temperature >= TEMP_WARNING:
        reasons.append("La temperatura alcanzó el umbral de advertencia.")
        if temperature >= TEMP_FIRE:
            strong_signals.append("temperature")
    if humidity <= HUMIDITY_DRY and temperature >= 35:
        reasons.append("La humedad es baja y la temperatura está elevada.")

    sensor_signal_count = len(reasons)
    if len(strong_signals) >= 2:
        level = "FIRE"
    elif sensor_signal_count:
        level = "WARNING"
    else:
        level = "NORMAL"

    if ai_probability is not None:
        if ai_probability >= 0.85 and sensor_signal_count:
            level = "FIRE"
            reasons.append("La probabilidad de IA alcanzó el nivel de emergencia.")
        elif ai_probability >= 0.5:
            if level == "NORMAL":
                level = "WARNING"
            reasons.append("La probabilidad de IA alcanzó el nivel de advertencia.")

    return {
        "level": level,
        "reasons": reasons,
        "ai_probability": ai_probability,
    }