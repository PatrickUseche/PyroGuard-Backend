import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import Node, NodeLink, RiskAssessment, SensorReading
from api.services.alerts import maybe_create_alert
from api.services.risk_rules import SMOKE_FIRE, SMOKE_WARNING, TEMP_FIRE, TEMP_WARNING, evaluate_risk

PREFIX = "SIM-"
INTERVAL_MINUTES = 10
LATEST_MINUTES = 30  # cuánto dura la situación de riesgo al final de la serie
OFFLINE_HOURS = 2  # el último nodo deja de comunicarse hace este tiempo


def reading_values(rng, scenario):
    """Valores de una lectura según el escenario (los umbrales vienen de risk_rules.py)."""
    humidity = round(rng.uniform(40, 80), 1)
    gas = round(rng.uniform(0, 15), 1)
    if scenario == "fire":
        return {
            "temperature": round(rng.uniform(TEMP_FIRE, 60), 1),
            "humidity": round(rng.uniform(10, 25), 1),
            "smoke": round(rng.uniform(SMOKE_FIRE, 90), 1),
            "gas": gas,
            "flame": True,
        }
    if scenario == "warning":
        return {
            "temperature": round(rng.uniform(TEMP_WARNING, TEMP_FIRE - 5), 1),
            "humidity": humidity,
            "smoke": round(rng.uniform(SMOKE_WARNING, SMOKE_FIRE - 5), 1),
            "gas": gas,
            "flame": False,
        }
    return {
        "temperature": round(rng.uniform(15, 30), 1),
        "humidity": humidity,
        "smoke": round(rng.uniform(10, 30), 1),
        "gas": gas,
        "flame": False,
    }


class Command(BaseCommand):
    help = (
        "Crea nodos SIM-001... enlazados entre sí, con horas de lecturas de ejemplo: el primero "
        "termina en FIRE, el segundo en WARNING (forman una zona de riesgo), el último queda "
        "desconectado y el resto está normal. No usa la IA ni red."
    )

    def add_arguments(self, parser):
        parser.add_argument("--nodes", type=int, default=6, help="Cantidad de nodos (de 3 a 50; por defecto 6).")
        parser.add_argument("--hours", type=int, default=6, help="Horas de historial (de 3 a 72; por defecto 6).")
        parser.add_argument("--seed", type=int, default=None, help="Semilla para repetir exactamente los mismos datos.")
        parser.add_argument(
            "--reset",
            action="store_true",
            help=f"Borra antes los nodos {PREFIX}* (y sus lecturas, alertas y enlaces).",
        )

    def handle(self, *args, **options):
        nodes, hours = options["nodes"], options["hours"]
        if not 3 <= nodes <= 50:
            raise CommandError("--nodes debe estar entre 3 y 50.")
        if not 3 <= hours <= 72:
            raise CommandError("--hours debe estar entre 3 y 72.")

        existing = Node.objects.filter(node_id__startswith=PREFIX)
        if existing.exists():
            if not options["reset"]:
                raise CommandError(
                    f"Ya existen nodos {PREFIX}*. Usa --reset para borrarlos y volver a crearlos."
                )
            existing.delete()

        rng = random.Random(options["seed"])
        with transaction.atomic():
            created = self._create_nodes(nodes)
            self._link(created)
            readings = self._create_readings(created, hours, rng)

        self.stdout.write(
            self.style.SUCCESS(
                f"Se crearon {nodes} nodos, {NodeLink.objects.count()} vínculos y {readings} lecturas. "
                f"{created[0].node_id} en FIRE, {created[1].node_id} en WARNING y "
                f"{created[-1].node_id} desconectado."
            )
        )

    def _create_nodes(self, count):
        return [
            Node.objects.create(
                node_id=f"{PREFIX}{number:03d}",
                name=f"Nodo de demostración {number}",
                description="Creado por seed_demo",
                latitude=round(6.2442 + number * 0.002, 6),
                longitude=round(-75.5812 + number * 0.002, 6),
            )
            for number in range(1, count + 1)
        ]

    def _link(self, nodes):
        """Cadena 1-2-3-...-n cerrada en anillo, para tener vecinos y zonas."""
        pairs = list(zip(nodes, nodes[1:], strict=False))
        if len(nodes) > 2:
            pairs.append((nodes[-1], nodes[0]))
        for first, second in pairs:
            NodeLink.objects.create(node_a=first, node_b=second)

    def _scenario(self, index, count, minutes_ago):
        """Escenario del nodo ``index`` en el momento ``minutes_ago`` (0 = ahora)."""
        in_final_stretch = minutes_ago < LATEST_MINUTES
        if index == 0 and in_final_stretch:
            return "fire"
        if index == 1 and in_final_stretch:
            return "warning"
        return "normal"

    def _create_readings(self, nodes, hours, rng):
        now = timezone.now()
        total = 0
        for index, node in enumerate(nodes):
            is_offline = index == len(nodes) - 1
            latest_allowed = OFFLINE_HOURS * 60 if is_offline else 0
            readings = []
            for minutes_ago in range(hours * 60, latest_allowed - 1, -INTERVAL_MINUTES):
                values = reading_values(rng, self._scenario(index, len(nodes), minutes_ago))
                readings.append(
                    SensorReading(node=node, timestamp=now - timedelta(minutes=minutes_ago), **values)
                )
            SensorReading.objects.bulk_create(readings)
            saved = list(SensorReading.objects.filter(node=node).order_by("timestamp"))
            assessments = []
            for reading in saved:
                evaluation = evaluate_risk(
                    {
                        "temperature": reading.temperature,
                        "humidity": reading.humidity,
                        "smoke": reading.smoke,
                        "flame": reading.flame,
                    }
                )
                assessments.append(
                    RiskAssessment(
                        reading=reading,
                        risk_level=evaluation["level"],
                        rule_reasons=evaluation["reasons"],
                    )
                )
            RiskAssessment.objects.bulk_create(assessments)
            last = saved[-1]
            Node.objects.filter(pk=node.pk).update(last_communication=last.timestamp)
            last_assessment = RiskAssessment.objects.get(reading=last)
            maybe_create_alert(node, last, last_assessment)
            total += len(saved)
        return total
