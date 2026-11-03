from django.conf import settings
from django.core.mail import send_mail

from .base import NotificationError, Notifier


class EmailNotifier(Notifier):
    """Envía el aviso por correo a ``NOTIFY_EMAIL_TO`` con la configuración SMTP de Django."""

    name = "email"

    def is_configured(self):
        return bool(settings.NOTIFY_EMAIL_TO)

    def send(self, notification):
        try:
            sent = send_mail(
                subject=f"[PyroGuard] {notification.subject}",
                message=notification.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=list(settings.NOTIFY_EMAIL_TO),
                fail_silently=False,
            )
        except Exception as error:  # noqa: BLE001 - SMTP puede fallar de muchas formas
            raise NotificationError(f"No se pudo enviar el correo ({type(error).__name__}).") from None
        if not sent:
            raise NotificationError("El servidor de correo no aceptó el mensaje.")
