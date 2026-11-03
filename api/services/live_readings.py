"""Estado en memoria de las lecturas de cada nodo.

Guarda, por nodo, un buffer circular con las últimas lecturas ya serializadas, de
modo que ``GET /nodes/{id}/recent/`` se responde sin consultar la base. Un nodo
se carga una sola vez desde la base la primera vez que se consulta (carga
perezosa) y desde entonces la ingesta lo mantiene al día. Los nodos que nadie ha
consultado no ocupan memoria ni cuestan nada en la ingesta.

Límites que conviene conocer: el estado vive en el proceso, así que se pierde al
reiniciar y cada worker de gunicorn tiene el suyo; el orden del buffer es el de
llegada, no el del ``timestamp`` de la lectura.
"""
from django.conf import settings

from api.models import SensorReading
from api.serializers import SensorReadingSerializer
from api.structures.recent_items_ring import RecentItemsRing


class LiveReadingsStore:
    def __init__(self):
        self._rings = {}

    def clear(self):
        self._rings.clear()

    def is_loaded(self, node_id):
        return node_id in self._rings

    def load(self, node):
        """Llena el buffer del nodo con sus últimas lecturas de la base."""
        ring = RecentItemsRing(settings.RECENT_READINGS_PER_NODE)
        latest = (
            SensorReading.objects.filter(node=node)
            .select_related("node", "assessment")
            .order_by("-timestamp", "-pk")[: ring.capacity]
        )
        for reading in reversed(list(latest)):
            ring.append(dict(SensorReadingSerializer(reading).data))
        self._rings[node.node_id] = ring
        return ring

    def record(self, reading):
        """Agrega una lectura recién ingerida al buffer, si el nodo ya está cargado."""
        ring = self._rings.get(reading.node.node_id)
        if ring is not None:
            ring.append(dict(SensorReadingSerializer(reading).data))

    def recent(self, node, limit=None):
        """Lecturas del nodo de la más nueva a la más antigua, cargándolo si hace falta."""
        ring = self._rings.get(node.node_id)
        if ring is None:
            ring = self.load(node)
        readings = list(ring)
        readings.reverse()
        return readings if limit is None else readings[:limit]


live_readings = LiveReadingsStore()
