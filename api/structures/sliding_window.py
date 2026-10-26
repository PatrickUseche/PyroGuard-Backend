import math


class _MonotonicQueue:
    """Cola doble mínima de pares (posición, valor) con los valores ordenados.

    Con ``keeps_larger`` los valores quedan de mayor a menor, y el primero es el
    máximo de la ventana; si no, de menor a mayor y el primero es el mínimo.
    Se apoya en una lista y un índice de cabeza: sacar por el frente avanza el
    índice y sacar por el final es ``list.pop()``.
    """

    _COMPACT_AFTER = 64

    def __init__(self, keeps_larger):
        self._keeps_larger = keeps_larger
        self._items = []
        self._head = 0

    def _loses_to(self, stored, incoming):
        # Un valor guardado que no supera al nuevo ya no puede ser el extremo,
        # porque el nuevo es más reciente y saldrá de la ventana después.
        return stored <= incoming if self._keeps_larger else stored >= incoming

    def push(self, position, value):
        while len(self._items) > self._head and self._loses_to(self._items[-1][1], value):
            self._items.pop()
        self._items.append((position, value))

    def expire_before(self, position):
        """Descarta del frente lo que quedó fuera de la ventana."""
        while self._head < len(self._items) and self._items[self._head][0] < position:
            self._head += 1
        if self._head >= self._COMPACT_AFTER and self._head * 2 >= len(self._items):
            del self._items[: self._head]
            self._head = 0

    def front(self):
        return self._items[self._head][1]


class SlidingWindow:
    """Máximo y mínimo de los últimos ``size`` valores, sin recorrer la ventana.

    Cada valor entra y sale de cada cola una sola vez, así que el costo de
    ``push`` es constante en promedio aunque a veces descarte varios valores.

    Complejidad (``w`` = tamaño de la ventana):
        push(value) -- O(1) amortizado
        maximum / minimum -- O(1)
        recalcular recorriendo la ventana -- O(w) por consulta (lo que se evita)
        espacio -- O(w) en el peor caso
    """

    def __init__(self, size):
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ValueError("El tamaño de la ventana debe ser un entero mayor o igual que 1.")
        self._size = size
        self._pushed = 0
        self._maxima = _MonotonicQueue(keeps_larger=True)
        self._minima = _MonotonicQueue(keeps_larger=False)

    @property
    def size(self):
        return self._size

    def __len__(self):
        return min(self._pushed, self._size)

    def is_empty(self):
        return self._pushed == 0

    def is_full(self):
        return self._pushed >= self._size

    def push(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("La ventana solo acepta números.")
        if isinstance(value, float) and math.isnan(value):
            raise ValueError("La ventana no acepta NaN.")

        position = self._pushed
        self._pushed += 1
        self._maxima.push(position, value)
        self._minima.push(position, value)

        oldest_position = self._pushed - self._size
        self._maxima.expire_before(oldest_position)
        self._minima.expire_before(oldest_position)

    @property
    def maximum(self):
        if self.is_empty():
            raise ValueError("La ventana está vacía.")
        return self._maxima.front()

    @property
    def minimum(self):
        if self.is_empty():
            raise ValueError("La ventana está vacía.")
        return self._minima.front()
