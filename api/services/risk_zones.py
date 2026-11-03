"""Zonas de riesgo: grupos de nodos vecinos que están en riesgo a la vez.

Una zona es un conjunto de nodos en ``WARNING`` o ``FIRE`` conectados entre sí por
enlaces de vecindad (directos o a través de otros nodos de la misma zona). Se
agrupan con ``DisjointSetUnion``: cada nodo en riesgo empieza en su propio conjunto
y se une a sus vecinos que también lo están, lo que cuesta O((V + E) α(V)) en lugar
de repetir un recorrido por cada nodo.

Igual que el resumen del dashboard, solo cuentan los nodos conectados
(``ONLINE``): el riesgo de un nodo desconectado es historial, no una situación
actual confirmada.
"""
from django.conf import settings
from django.utils import timezone

from api.services.node_graph import node_graph
from api.services.nodes import RISK_PRIORITY, nodes_with_current_risk
from api.structures.disjoint_set_union import DisjointSetUnion

AT_RISK_LEVELS = ("WARNING", "FIRE")


def get_risk_zones():
    """Zonas de riesgo actuales, de la más grave a la menos grave.

    Se ordenan por el nivel más alto de la zona, luego por tamaño (mayor primero)
    y luego por el primer ``node_id``, que además es su ``zone_id``.
    """
    offline_cutoff = timezone.now() - timezone.timedelta(
        seconds=settings.NODE_OFFLINE_THRESHOLD_SECONDS
    )
    at_risk = dict(
        nodes_with_current_risk()
        .filter(last_communication__gte=offline_cutoff, current_risk__in=AT_RISK_LEVELS)
        .values_list("node_id", "current_risk")
    )

    zones_of_nodes = DisjointSetUnion(sorted(at_risk))
    for node_id in at_risk:
        for neighbor in node_graph.direct_neighbors(node_id):
            if neighbor in at_risk:
                zones_of_nodes.union(node_id, neighbor)

    zones = []
    for members in zones_of_nodes.groups():
        members.sort()
        highest = max((at_risk[node_id] for node_id in members), key=RISK_PRIORITY.get)
        zones.append(
            {
                "zone_id": members[0],
                "risk_level": highest,
                "size": len(members),
                "nodes": [{"node_id": node_id, "current_risk": at_risk[node_id]} for node_id in members],
            }
        )
    zones.sort(key=lambda zone: (-RISK_PRIORITY[zone["risk_level"]], -zone["size"], zone["zone_id"]))
    return zones
