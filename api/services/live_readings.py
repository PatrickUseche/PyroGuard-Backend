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
from api.structures.rolling_extremes_window import RollingExtremesWindow


class LiveReadingsStore:
    def __init__(self):
        self._rings = {}
        self._windows = {}

    def clear(self):
        self._rings.clear()
        self._windows.clear()

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
        """Agrega una lectura recién ingerida a lo que ya esté cargado del nodo."""
        node_id = reading.node.node_id
        ring = self._rings.get(node_id)
        if ring is not None:
            ring.append(dict(SensorReadingSerializer(reading).data))
        window = self._windows.get(node_id)
        if window is not None:
            window.push(reading.temperature)

    def recent(self, node, limit=None):
        """Lecturas del nodo de la más nueva a la más antigua, cargándolo si hace falta."""
        ring = self._rings.get(node.node_id)
        if ring is None:
            ring = self.load(node)
        readings = list(ring)
        readings.reverse()
        return readings if limit is None else readings[:limit]

    def is_window_loaded(self, node_id):
        return node_id in self._windows

    def load_window(self, node_id):
        """Llena la ventana de temperatura del nodo con sus últimas lecturas."""
        window = RollingExtremesWindow(settings.TEMPERATURE_WINDOW_SIZE)
        latest = (
            SensorReading.objects.filter(node__node_id=node_id)
            .order_by("-timestamp", "-pk")
            .values_list("temperature", flat=True)[: window.size]
        )
        for temperature in reversed(list(latest)):
            window.push(temperature)
        self._windows[node_id] = window
        return window

    def temperature_window(self, node_id):
        """Máximo y mínimo de las últimas lecturas del nodo, o ``None`` si no tiene.

        Devuelve ``{"size": tamaño de la ventana, "readings": cuántas contiene,
        "max": ..., "min": ...}``. Cuesta O(1) una vez cargada la ventana.
        """
        window = self._windows.get(node_id)
        if window is None:
            window = self.load_window(node_id)
        if window.is_empty():
            return None
        return {
            "size": window.size,
            "readings": len(window),
            "max": window.maximum,
            "min": window.minimum,
        }


live_readings = LiveReadingsStore()
