import argparse
import os
import random
import time
from datetime import datetime, timezone

import requests

from api.services.risk_rules import SMOKE_FIRE, SMOKE_WARNING, TEMP_FIRE, TEMP_WARNING


def parse_args():
    parser = argparse.ArgumentParser(description="Simulador IoT de PyroGuard")
    parser.add_argument(
        "--url",
        default=os.getenv("API_URL", "http://localhost:8000/api/readings/"),
        help="URL de ingesta de lecturas",
    )
    parser.add_argument("--node", default="NODE-001", help="Identificador del nodo")
    parser.add_argument(
        "--interval",
        type=float,
        default=5,
        help="Intervalo en segundos entre lecturas",
    )
    parser.add_argument(
        "--scenario",
        choices=("normal", "warning", "fire", "random"),
        default="random",
        help="Escenario de lecturas",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("INGEST_API_KEY", ""),
        help="Clave API de ingesta (por defecto, INGEST_API_KEY)",
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval debe ser mayor que cero.")
    return args


def generate_simulated_data(node_id, scenario="random"):
    """Genera un escenario; los límites siguen risk_rules.py del prototipo."""
    selected_scenario = scenario
    if scenario == "random":
        selected_scenario = random.choices(
            ("normal", "warning", "fire"),
            weights=(85, 10, 5),
            k=1,
        )[0]

    humidity = round(random.uniform(40, 80), 1)
    gas = round(random.uniform(0, 15), 1)
    if selected_scenario == "normal":
        temperature = round(random.uniform(15, 30), 1)
        smoke = round(random.uniform(10, 30), 1)
        flame = False
    elif selected_scenario == "warning":
        if random.choice((True, False)):
            temperature = round(random.uniform(TEMP_WARNING, TEMP_FIRE - 5), 1)
            smoke = round(random.uniform(10, SMOKE_WARNING - 1), 1)
        else:
            temperature = round(random.uniform(15, TEMP_WARNING - 1), 1)
            smoke = round(random.uniform(SMOKE_WARNING, SMOKE_FIRE - 5), 1)
        flame = False
    else:
        temperature = round(random.uniform(TEMP_FIRE, 60), 1)
        smoke = round(random.uniform(SMOKE_FIRE, 90), 1)
        flame = True

    return {
        "node_id": node_id,
        "temperature": temperature,
        "humidity": humidity,
        "smoke": smoke,
        "gas": gas,
        "flame": flame,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, selected_scenario


def send_data(args):
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    print(
        f"Simulador PyroGuard para {args.node}; destino {args.url}; "
        f"escenario {args.scenario}; intervalo {args.interval}s."
    )
    if not args.api_key:
        print("Aviso: no se enviará X-API-Key; el servidor debe permitir ingesta local.")

    try:
        while True:
            payload, scenario = generate_simulated_data(args.node, args.scenario)
            print(
                "SIMULADO | "
                f"escenario={scenario} nodo={args.node} "
                f"temperatura={payload['temperature']}C "
                f"humedad={payload['humidity']}% humo={payload['smoke']} "
                f"gas={payload['gas']} llama={payload['flame']}"
            )
            try:
                response = requests.post(
                    args.url,
                    json=payload,
                    headers=headers,
                    timeout=10,
                )
                if response.status_code == 201:
                    print("Envío exitoso.")
                else:
                    print(
                        f"Error en el envío. Código: {response.status_code}. "
                        f"Respuesta: {response.text}"
                    )
            except requests.exceptions.RequestException as error:
                print(
                    "No se pudo conectar al servidor. "
                    f"Tipo de error: {error}"
                )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nSimulador detenido por el usuario.")


if __name__ == "__main__":
    send_data(parse_args())