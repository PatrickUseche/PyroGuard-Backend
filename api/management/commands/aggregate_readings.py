from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Max, Min, Q
from django.db.models.functions import TruncHour

from api.models import ReadingHourly, SensorReading


class Command(BaseCommand):
    help = (
        "Rellena ReadingHourly con el resumen por hora de las lecturas de cada nodo. "
        "Es idempotente: por defecto recalcula desde la última hora ya resumida. "
        "No uses --all después de purgar lecturas: sobrescribiría con datos incompletos."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Recalcula todas las horas con lecturas, no solo las nuevas.",
        )

    def handle(self, *args, **options):
        readings = SensorReading.objects.all()
        if not options["all"]:
            last = ReadingHourly.objects.order_by("-hour").values_list("hour", flat=True).first()
            if last is not None:
                # La última hora pudo resumirse incompleta, así que se recalcula.
                readings = readings.filter(timestamp__gte=last)

        rows = (
            readings.annotate(hour=TruncHour("timestamp", tzinfo=None))
            .values("node_id", "hour")
            .annotate(
                reading_count=Count("pk"),
                temperature_min=Min("temperature"),
                temperature_avg=Avg("temperature"),
                temperature_max=Max("temperature"),
                humidity_avg=Avg("humidity"),
                smoke_max=Max("smoke"),
                flame_count=Count("pk", filter=Q(flame=True)),
            )
        )
        hourly = [
            ReadingHourly(
                node_id=row["node_id"],
                hour=row["hour"],
                reading_count=row["reading_count"],
                temperature_min=row["temperature_min"],
                temperature_avg=row["temperature_avg"],
                temperature_max=row["temperature_max"],
                humidity_avg=row["humidity_avg"],
                smoke_max=row["smoke_max"],
                flame_count=row["flame_count"],
            )
            for row in rows
        ]
        ReadingHourly.objects.bulk_create(
            hourly,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["node", "hour"],
            update_fields=[
                "reading_count",
                "temperature_min",
                "temperature_avg",
                "temperature_max",
                "humidity_avg",
                "smoke_max",
                "flame_count",
            ],
        )
        self.stdout.write(self.style.SUCCESS(f"Se resumieron {len(hourly)} hora(s) de lecturas."))
