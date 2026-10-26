"""Estructuras de datos propias del backend.

Se implementan a mano, sin apoyarse en ``collections.deque``, ``heapq`` ni
``functools.lru_cache``, para poder razonar y medir su complejidad. Cada clase
documenta el costo de sus operaciones en su docstring con el formato::

    Complejidad:
        operacion -- O(...)

donde ``n`` es el número de elementos guardados y ``k`` la capacidad. Después se
usan en funcionalidades reales del backend (ver ``docs/ESTRUCTURAS_DE_DATOS.md``).

Seguridad entre hilos: ninguna de estas estructuras es segura si varios hilos las
modifican a la vez. Quien comparta una instancia entre peticiones debe protegerla
con un ``threading.Lock``. Además, cada proceso del servidor tiene su propia copia:
con varios workers de gunicorn las instancias no se comparten ni se sincronizan.
"""
