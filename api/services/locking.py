"""Candado para el estado en memoria que comparten las peticiones.

Gunicorn puede atender varias peticiones a la vez en hilos del mismo proceso, y las
estructuras de ``api/structures`` no son seguras entre hilos. Cada servicio con
estado crea un ``threading.RLock`` en ``self._lock`` y marca sus métodos públicos con
``@synchronized``, de modo que solo un hilo a la vez toca la estructura. Es un
``RLock`` porque unos métodos llaman a otros (por ejemplo, ``recent`` llama a ``load``).

El candado solo protege los hilos de **un** proceso. Cada worker de gunicorn es un
proceso aparte con su propia copia del estado: no se comparte ni se sincroniza entre
ellos (ver «Estado en memoria» en el README).
"""
import functools


def synchronized(method):
    """Ejecuta el método con ``self._lock`` tomado."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper
