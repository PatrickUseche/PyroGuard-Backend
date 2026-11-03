import requests
from django.conf import settings

from .base import NotificationError, Notifier

TELEGRAM_TIMEOUT_SECONDS = 10


class TelegramNotifier(Notifier):
    """Envía el aviso a un chat de Telegram con la API de bots."""

    name = "telegram"

    def is_configured(self):
        return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)

    def send(self, notification):
        # El token va en la URL: nunca se registra ni se incluye en los errores.
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            response = requests.post(
                url,
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": f"{notification.subject}\n\n{notification.message}",
                },
                timeout=TELEGRAM_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise NotificationError(
                f"No se pudo contactar con Telegram ({type(error).__name__})."
            ) from None
        if response.status_code != 200:
            raise NotificationError(f"Telegram rechazó el aviso (HTTP {response.status_code}).")
