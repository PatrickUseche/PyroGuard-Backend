from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import SensorReading


class Command(BaseCommand):
    help = (
        "Borra las lecturas más antiguas que la retención (READINGS_RETENTION_DAYS). "
        "Las lecturas que originaron una alerta se conservan para no perder el historial."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Días de retención; por defecto READINGS_RETENTION_DAYS.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Lecturas que se borran por consulta (por defecto 1000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo cuenta lo que se borraría, sin borrar nada.",
        )

    def handle(self, *args, **options):
        days = options["days"] if options["days"] is not None else settings.READINGS_RETENTION_DAYS
        batch_size = options["batch_size"]
        if days < 1:
            raise CommandError("--days debe ser un entero mayor o igual que 1.")
        if batch_size < 1:
            raise CommandError("--batch-size debe ser un entero mayor o igual que 1.")

        cutoff = timezone.now() - timedelta(days=days)
        expired = SensorReading.objects.filter(timestamp__lt=cutoff, alerts__isnull=True)

        if options["dry_run"]:
            self.stdout.write(
                f"Se borrarían {expired.count()} lectura(s) anteriores a {cutoff:%Y-%m-%d %H:%M} UTC."
            )
            return

        deleted = 0
        while True:
            batch = list(expired.values_list("pk", flat=True)[:batch_size])
            if not batch:
                break
            SensorReading.objects.filter(pk__in=batch).delete()
            deleted += len(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"Se borraron {deleted} lectura(s) anteriores a {cutoff:%Y-%m-%d %H:%M} UTC "
                f"(retención: {days} días)."
            )
        )
