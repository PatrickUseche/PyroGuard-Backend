from django.core.management.base import BaseCommand, CommandError

from api.services.evaluation_queue import drain, pending_count


class Command(BaseCommand):
    help = (
        "Evalúa con la IA las lecturas que quedaron pendientes (AI_ASYNC_EVALUATION=True), "
        "de la más antigua a la más nueva. Si la IA no responde se detiene y deja el resto pendiente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Máximo de evaluaciones que atiende en esta ejecución (por defecto 500).",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit debe ser un entero mayor o igual que 1.")

        result = drain(limit)
        remaining = pending_count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Evaluadas: {result.evaluated}. Ya atendidas por otro proceso: {result.skipped}. "
                f"Pendientes: {remaining}."
            )
        )
        if result.stopped_early:
            self.stdout.write(
                self.style.WARNING("La IA no respondió: se detuvo antes de vaciar la cola.")
            )
