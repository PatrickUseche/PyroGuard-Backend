from django.core.management.base import BaseCommand, CommandError

from api.services.evaluation_queue import drain, pending_count, repair_unassessed


class Command(BaseCommand):
    help = (
        "Evalúa con la IA las lecturas que quedaron pendientes (AI_ASYNC_EVALUATION=True), "
        "de la más antigua a la más nueva. Si la IA no responde se detiene y deja el resto pendiente. "
        "También repara las lecturas que se guardaron sin evaluación por un fallo posterior."
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

        repaired = repair_unassessed(limit)
        result = drain(limit)
        remaining = pending_count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Reparadas sin evaluación: {repaired}. "
                f"Evaluadas: {result.evaluated}. Ya atendidas por otro proceso: {result.skipped}. "
                f"Pendientes: {remaining}."
            )
        )
        if result.stopped_early:
            self.stdout.write(
                self.style.WARNING("La IA no respondió: se detuvo antes de vaciar la cola.")
            )
