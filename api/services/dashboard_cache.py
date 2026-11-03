"""Caché LRU del resumen del dashboard con caducidad corta.

El resumen cuenta todos los nodos y consulta sus últimas lecturas, que es lo más
caro de la API y lo que el frontend repite cada pocos segundos. Se reutiliza
durante ``DASHBOARD_CACHE_SECONDS`` y además se descarta en cuanto cambia un dato
del que depende (señales de ``api/cache_signals.py``). La caducidad cubre lo que
no genera señales, como que un nodo pase a OFFLINE por el simple paso del tiempo.

Cada worker tiene su propia caché y se pierde al reiniciar.
"""
import copy
import threading
import time

from django.conf import settings

from api.services.locking import synchronized
from api.structures.least_recently_used_cache import LeastRecentlyUsedCache

_SUMMARY_KEY = "summary"


class DashboardSummaryCache:
    def __init__(self, clock=time.monotonic):
        self._lock = threading.RLock()
        self._clock = clock
        # Hoy solo hay un resumen, pero la LRU deja lista la caché para guardar
        # variantes (por ejemplo, un resumen por zona) sin crecer sin límite.
        self._lru = LeastRecentlyUsedCache(4)

    @synchronized
    def get(self):
        """Devuelve una copia del resumen si sigue vigente; si no, ``None``."""
        if settings.DASHBOARD_CACHE_SECONDS <= 0:
            return None
        entry = self._lru.get(_SUMMARY_KEY)
        if entry is None:
            return None
        expires_at, summary = entry
        if self._clock() >= expires_at:
            self._lru.discard(_SUMMARY_KEY)
            return None
        return copy.deepcopy(summary)

    @synchronized
    def put(self, summary):
        seconds = settings.DASHBOARD_CACHE_SECONDS
        if seconds > 0:
            self._lru.put(_SUMMARY_KEY, (self._clock() + seconds, copy.deepcopy(summary)))

    @synchronized
    def invalidate(self):
        self._lru.discard(_SUMMARY_KEY)

    clear = invalidate

    @property
    @synchronized
    def stats(self):
        return {"hits": self._lru.hits, "misses": self._lru.misses, "size": len(self._lru)}


dashboard_cache = DashboardSummaryCache()
