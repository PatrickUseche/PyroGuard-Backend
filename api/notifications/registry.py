import logging

from django.conf import settings

from .console import ConsoleNotifier
from .email_channel import EmailNotifier
from .telegram_channel import TelegramNotifier

logger = logging.getLogger("api.notifications")

CHANNELS = {
    notifier.name: notifier
    for notifier in (ConsoleNotifier, EmailNotifier, TelegramNotifier)
}


def active_notifiers():
    """Canales de ``NOTIFICATION_CHANNELS`` que están bien configurados."""
    notifiers = []
    for name in settings.NOTIFICATION_CHANNELS:
        notifier = CHANNELS[name]()
        if notifier.is_configured():
            notifiers.append(notifier)
        else:
            logger.warning("El canal de notificación '%s' está activado pero le falta configuración.", name)
    return notifiers
