from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Alert, Node, NotificationOutbox
from api.notifications.outbox import enqueue


class Command(BaseCommand):
    help = (
        "Lista los nodos que llevan más de NODE_OFFLINE_THRESHOLD_SECONDS sin comunicarse "
        "(los que nunca se han comunicado no cuentan: su estado es UNKNOWN) y encola un aviso "
        "por cada uno que tiene una alerta activa."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-notify",
            action="store_true",
            help="Solo lista los nodos, sin encolar avisos.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(seconds=settings.NODE_OFFLINE_THRESHOLD_SECONDS)
        offline = list(
            Node.objects.filter(last_communication__lt=cutoff).order_by("last_communication", "node_id")
        )

        if not offline:
            self.stdout.write(self.style.SUCCESS("Todos los nodos que se han comunicado están conectados."))
            return

        self.stdout.write(f"Nodos desconectados: {len(offline)}")
        now = timezone.now()
        for node in offline:
            minutes = int((now - node.last_communication).total_seconds() // 60)
            self.stdout.write(f"- {node.node_id}: sin comunicación desde hace {minutes} min")

        if options["no_notify"]:
            return
        queued = sum(1 for node in offline if self._notify_if_alerting(node))
        self.stdout.write(f"Avisos encolados: {queued}.")

    def _notify_if_alerting(self, node):
        """Encola un aviso si el nodo desconectado tiene una alerta activa; ``True`` si se encoló."""
        alert = (
            Alert.objects.filter(
                node=node,
                status__in=[Alert.Status.ACTIVE, Alert.Status.ACKNOWLEDGED],
            )
            .order_by("-level", "-created_at")  # FIRE antes que WARNING
            .first()
        )
        if alert is None:
            return False
        notice = enqueue(
            NotificationOutbox.Kind.OFFLINE_ALERT,
            node,
            f"El nodo {node.node_id} está desconectado con una alerta {alert.level} activa",
            (
                f"El nodo {node.node_id} no se comunica desde "
                f"{node.last_communication:%Y-%m-%d %H:%M} UTC y tiene una alerta {alert.level} "
                f"({alert.get_status_display()}). Su riesgo actual es desconocido: puede haber "
                "perdido la conexión por el propio incendio."
            ),
        )
        return notice is not None
