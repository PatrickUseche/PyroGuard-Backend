"""Detección de lecturas duplicadas (mismo nodo y mismo ``timestamp``).

Un sensor que reintenta un envío mandaría la misma lectura dos veces. Para no
consultar la base en cada ingesta se usa un ``DuplicateBloomFilter``:

* Si el filtro dice **no**, la lectura es nueva y se guarda sin consultar nada.
* Si dice **sí**, puede ser un falso positivo, así que se **confirma en la base**
  antes de descartarla. Nunca se descarta una lectura solo por el filtro.

El filtro vive en el proceso y empieza vacío al arrancar, por lo que se rellena
con las últimas lecturas de la base la primera vez que se usa. Eso significa que
un duplicado de una lectura muy antigua (fuera de esa ventana) o de otro worker
podría no detectarse; en el peor caso se guarda repetida, nunca se pierde un dato.
Cuando el filtro recibe más lecturas de las que fue dimensionado, se reconstruye.
"""
import threading
from datetime import timezone

from django.conf import settings

from api.models import SensorReading
from api.structures.duplicate_bloom_filter import DuplicateBloomFilter
from api.services.locking import synchronized

FALSE_POSITIVE_RATE = 0.01


def reading_key(node_id, timestamp):
    """Clave estable de una lectura: nodo y momento en UTC con microsegundos."""
    return (node_id, timestamp.astimezone(timezone.utc).isoformat())


class DuplicateReadingDetector:
    def __init__(self):
        self._lock = threading.RLock()
        self._filter = None
        self._capacity = None

    @synchronized
    def clear(self):
        self._filter = None
        self._capacity = None

    def _current_filter(self):
        capacity = settings.DUPLICATE_FILTER_CAPACITY
        needs_rebuild = (
            self._filter is None
            or self._capacity != capacity
            or len(self._filter) >= capacity
        )
        if needs_rebuild:
            self._filter = DuplicateBloomFilter(capacity, FALSE_POSITIVE_RATE)
            self._capacity = capacity
            self._warm_up(capacity // 2)
        return self._filter

    def _warm_up(self, how_many):
        latest = (
            SensorReading.objects.order_by("-timestamp", "-pk")
            .values_list("node__node_id", "timestamp")[:how_many]
        )
        for node_id, timestamp in latest:
            self._filter.add(reading_key(node_id, timestamp))

    @synchronized
    def find(self, node_id, timestamp):
        """Devuelve la lectura ya guardada con ese nodo y momento, o ``None``."""
        if not settings.DEDUPLICATE_READINGS:
            return None
        if reading_key(node_id, timestamp) not in self._current_filter():
            return None
        return (
            SensorReading.objects.filter(node__node_id=node_id, timestamp=timestamp)
            .select_related("node", "assessment")
            .order_by("pk")
            .first()
        )

    @synchronized
    def remember(self, node_id, timestamp):
        """Anota una lectura recién guardada para detectar sus repeticiones."""
        if settings.DEDUPLICATE_READINGS:
            self._current_filter().add(reading_key(node_id, timestamp))


duplicate_readings = DuplicateReadingDetector()
