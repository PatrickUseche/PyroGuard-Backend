"""Caché LRU del estado de cada nodo (``GET /nodes/{id}/status/``).

Guarda lo que cuesta calcular con la base (última lectura, último riesgo y
alertas activas). Lo que depende del reloj o de la memoria (``connection_status``
y la ventana de temperatura) no se cachea: se calcula en cada petición.

La entrada de un nodo se invalida cada vez que cambia algo que la afecta; eso lo
hacen las señales de ``api/cache_signals.py`` y, por seguridad, también el final
de la ingesta. El estado vive en el proceso: cada worker tiene su caché y se
pierde al reiniciar.
"""
import copy

from django.conf import settings

from api.structures.least_recently_used_cache import LeastRecentlyUsedCache


class NodeStatusCache:
    def __init__(self):
        self._lru = None

    def _cache(self):
        capacity = settings.NODE_STATUS_CACHE_SIZE
        if capacity == 0:
            return None
        if self._lru is None or self._lru.capacity != capacity:
            self._lru = LeastRecentlyUsedCache(capacity)
        return self._lru

    def get(self, node_id):
        """Devuelve una copia de lo guardado para el nodo, o ``None`` si no hay."""
        cache = self._cache()
        if cache is None:
            return None
        stored = cache.get(node_id)
        return None if stored is None else copy.deepcopy(stored)

    def put(self, node_id, status):
        cache = self._cache()
        if cache is not None:
            cache.put(node_id, copy.deepcopy(status))

    def invalidate(self, node_id):
        if self._lru is not None:
            self._lru.discard(node_id)

    def clear(self):
        if self._lru is not None:
            self._lru.clear()

    @property
    def stats(self):
        """Aciertos y fallos acumulados, útiles para medir si la caché sirve."""
        if self._lru is None:
            return {"hits": 0, "misses": 0, "size": 0}
        return {"hits": self._lru.hits, "misses": self._lru.misses, "size": len(self._lru)}


node_status_cache = NodeStatusCache()
