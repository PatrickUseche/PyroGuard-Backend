from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Node


class Command(BaseCommand):
    help = (
        "Lista los nodos que llevan más de NODE_OFFLINE_THRESHOLD_SECONDS sin comunicarse "
        "(los que nunca se han comunicado no cuentan: su estado es UNKNOWN)."
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
