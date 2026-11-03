"""Cola de avisos: se encolan en la base y se envían por prioridad.

* ``enqueue`` guarda un aviso pendiente.
* ``pending_heap`` ordena los pendientes con un ``PriorityMinHeap``: primero los más
  urgentes y, a igual urgencia, los más antiguos.
* ``send_pending`` los saca del montículo uno a uno y los entrega por cada canal activo.
"""
import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from api.models import NotificationOutbox
from api.structures.priority_min_heap import PriorityMinHeap

from .base import Notification, NotificationError
from .registry import active_notifiers

logger = logging.getLogger("api.notifications")

Kind = NotificationOutbox.Kind
Status = NotificationOutbox.Status

PRIORITY = {Kind.FIRE_ALERT: 1, Kind.OFFLINE_ALERT: 2}


def outbox_priority(row):
    """Menor sale primero: urgencia, luego antigüedad, luego id."""
    return (row.priority, row.created_at, row.pk)


def enqueue(kind, node, subject, message):
    """Guarda un aviso pendiente en la cola."""
    return NotificationOutbox.objects.create(
        node=node,
        kind=kind,
        priority=PRIORITY[kind],
        subject=subject[:200],
        message=message,
    )


def pending_heap(limit=None):
    """Montículo con los avisos pendientes (más urgente y más antiguo arriba)."""
    rows = NotificationOutbox.objects.filter(status=Status.PENDING).select_related("node")
    if limit is not None:
        # Se acota por antigüedad para no cargar una cola enorme; el montículo reordena por urgencia.
        rows = rows.order_by("created_at", "pk")[:limit]
    return PriorityMinHeap.from_items(rows, priority=outbox_priority)


@dataclass
class SendResult:
    sent: int = 0
    failed: int = 0
    retrying: int = 0


def send_pending(limit=100, notifiers=None):
    """Envía hasta ``limit`` avisos pendientes, los más urgentes primero.

    Un aviso queda ``SENT`` cuando lo recibieron todos los canales activos. Si algún canal
    falla se reintenta en la siguiente ejecución solo por los canales que faltan, y tras
    ``NOTIFICATION_MAX_ATTEMPTS`` intentos pasa a ``FAILED``.
    """
    notifiers = active_notifiers() if notifiers is None else notifiers
    heap = pending_heap(limit)
    result = SendResult()
    while not heap.is_empty():
        row = heap.pop()
        notification = Notification(
            subject=row.subject,
            message=row.message,
            node_id=row.node.node_id if row.node else "",
            priority=row.priority,
        )
        delivered = list(row.delivered_channels)
        errors = []
        for notifier in notifiers:
            if notifier.name in delivered:
                continue
            try:
                notifier.send(notification)
            except NotificationError as error:
                errors.append(f"{notifier.name}: {error}")
            else:
                delivered.append(notifier.name)

        row.delivered_channels = delivered
        row.attempts += 1
        if not errors and notifiers:
            row.status = Status.SENT
            row.sent_at = timezone.now()
            row.last_error = ""
            result.sent += 1
        elif row.attempts >= settings.NOTIFICATION_MAX_ATTEMPTS or not notifiers:
            row.status = Status.FAILED
            row.last_error = ("; ".join(errors) or "No hay canales activos.")[:300]
            result.failed += 1
        else:
            row.last_error = "; ".join(errors)[:300]
            result.retrying += 1
        row.save()
    return result
