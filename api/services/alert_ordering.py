"""Orden de urgencia de las alertas con un montículo mínimo.

Una alerta es más urgente cuanto más grave es su nivel (``FIRE`` antes que
``WARNING``) y, a igual gravedad, cuanto más tiempo lleva sin resolverse
(``created_at`` más antiguo primero). Si además coinciden en el instante, manda la
de menor ``pk``, para que el orden sea siempre el mismo.
"""
from api.structures.priority_min_heap import PriorityMinHeap

SEVERITY = {"FIRE": 2, "WARNING": 1}


def urgency(alert):
    """Prioridad de la alerta: la menor sale primero del montículo."""
    return (-SEVERITY.get(alert.level, 0), alert.created_at, alert.pk)


def order_by_urgency(alerts):
    """Todas las alertas de la más a la menos urgente: O(n + n log n)."""
    heap = PriorityMinHeap.from_items(alerts, priority=urgency)
    return [heap.pop() for _ in range(len(heap))]


def most_urgent(alerts, k):
    """Solo las ``k`` más urgentes: O(n + k log n), sin ordenar el resto."""
    return PriorityMinHeap.smallest(alerts, k, priority=urgency)
