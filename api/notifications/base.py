"""Interfaz común de los canales de notificación."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class NotificationError(Exception):
    """El canal no pudo entregar el aviso (el mensaje no debe incluir secretos)."""


@dataclass(frozen=True)
class Notification:
    subject: str
    message: str
    node_id: str = ""
    priority: int = 1  # menor = más urgente


class Notifier(ABC):
    """Un canal por el que se envían avisos (consola, correo, Telegram...)."""

    #: Nombre con el que se activa en ``NOTIFICATION_CHANNELS``.
    name = ""

    def is_configured(self):
        """``False`` si faltan datos para usar el canal; entonces no se usa."""
        return True

    @abstractmethod
    def send(self, notification):
        """Entrega el aviso o lanza ``NotificationError``."""
