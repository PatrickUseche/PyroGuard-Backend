from django.core.management.base import BaseCommand, CommandError

from api.models import NotificationOutbox
from api.notifications.outbox import send_pending


class Command(BaseCommand):
    help = (
        "Envía por los canales de NOTIFICATION_CHANNELS los avisos pendientes, "
        "los más urgentes primero (y, a igual urgencia, los más antiguos)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Máximo de avisos que atiende en esta ejecución (por defecto 100).",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit debe ser un entero mayor o igual que 1.")

        result = send_pending(limit)
        remaining = NotificationOutbox.objects.filter(status=NotificationOutbox.Status.PENDING).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Enviados: {result.sent}. Con reintento pendiente: {result.retrying}. "
                f"Fallidos: {result.failed}. En cola: {remaining}."
            )
        )
        if result.failed:
            self.stdout.write(
                self.style.WARNING("Hay avisos fallidos: revisa last_error en el admin de NotificationOutbox.")
            )
