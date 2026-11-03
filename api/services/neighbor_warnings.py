"""Aviso a los nodos vecinos cuando un nodo entra en ``FIRE``.

Un incendio en un nodo pone en riesgo a los cercanos, así que se recorre el grafo
de vecinos con un BFS hasta ``NEIGHBOR_WARNING_HOPS`` saltos. Hoy el aviso se
registra en el log y se devuelve; cuando existan canales de notificación (Fase 5)
este es el punto desde el que se mandarán.
"""
import logging

from django.conf import settings

from api.services.node_graph import node_graph

logger = logging.getLogger("api.readings")


def warn_neighbors_of_fire(node_id):
    """Avisa a los vecinos de ``node_id`` y devuelve ``{vecino: saltos}``."""
    hops = settings.NEIGHBOR_WARNING_HOPS
    if hops <= 0:
        return {}
    neighbors = node_graph.neighbors_within(node_id, hops)
    if neighbors:
        logger.warning(
            "Nodo %s en FIRE: aviso a %d nodo(s) vecino(s) a %d salto(s) o menos: %s",
            node_id,
            len(neighbors),
            hops,
            ", ".join(f"{neighbor} ({distance})" for neighbor, distance in neighbors.items()),
        )
    return neighbors
