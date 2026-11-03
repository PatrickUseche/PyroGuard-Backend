import logging

from .base import Notifier

logger = logging.getLogger("api.notifications")


class ConsoleNotifier(Notifier):
    """Escribe el aviso en el log; sirve en desarrollo y como respaldo."""

    name = "console"

    def send(self, notification):
        logger.warning(
            "AVISO [prioridad %s] %s | %s",
            notification.priority,
            notification.subject,
            notification.message,
        )
