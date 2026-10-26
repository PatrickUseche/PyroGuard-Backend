"""Estructuras de datos propias del backend.

Se implementan a mano, sin apoyarse en ``collections.deque``, ``heapq`` ni
``functools.lru_cache``, para poder razonar y medir su complejidad. Cada clase
documenta el costo de sus operaciones en su docstring con el formato::

    Complejidad:
        operacion -- O(...)

donde ``n`` es el número de elementos guardados y ``k`` la capacidad. Después se
usan en funcionalidades reales del backend (ver ``docs/ESTRUCTURAS_DE_DATOS.md``).
"""
