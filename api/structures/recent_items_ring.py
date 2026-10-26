class _NothingEvicted:
    """Marca «no se expulsó nada»; distinta de ``None``, que también se puede guardar."""

    __slots__ = ()

    def __repr__(self):
        return "NOTHING_EVICTED"

    def __bool__(self):
        return False


class RecentItemsRing:
    """Buffer circular de capacidad fija: al llenarse sobrescribe lo más antiguo.

    Guarda en un arreglo de tamaño fijo y mueve un índice de cabeza, así que
    insertar nunca desplaza elementos ni reserva memoria nueva.

    Complejidad (``k`` = capacidad, ``n`` = elementos guardados):
        append(item) -- O(1)
        oldest() / newest() -- O(1)
        buffer[i] -- O(1)
        iter(buffer) / list(buffer) -- O(n)
        RecentItemsRing(k) / clear() -- O(k), reservan o limpian las k posiciones
        espacio -- O(k), fijo desde que se crea (no crece con lo que se agrega)
    """

    NOTHING_EVICTED = _NothingEvicted()

    def __init__(self, capacity):
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise ValueError("La capacidad debe ser un entero mayor o igual que 1.")
        self._capacity = capacity
        self._slots = [None] * capacity
        self._head = 0  # posición del elemento más antiguo
        self._size = 0

    @property
    def capacity(self):
        return self._capacity

    def __len__(self):
        return self._size

    def is_empty(self):
        return self._size == 0

    def is_full(self):
        return self._size == self._capacity

    def append(self, item):
        """Agrega ``item`` como el más reciente y devuelve el elemento expulsado.

        Si todavía había lugar devuelve ``NOTHING_EVICTED``, no ``None``: así se
        distingue de haber expulsado un ``None`` guardado.
        """
        if self._size < self._capacity:
            self._slots[(self._head + self._size) % self._capacity] = item
            self._size += 1
            return self.NOTHING_EVICTED

        evicted = self._slots[self._head]
        self._slots[self._head] = item
        self._head = (self._head + 1) % self._capacity
        return evicted

    def oldest(self):
        if self._size == 0:
            raise IndexError("El buffer está vacío.")
        return self._slots[self._head]

    def newest(self):
        if self._size == 0:
            raise IndexError("El buffer está vacío.")
        return self._slots[(self._head + self._size - 1) % self._capacity]

    def __getitem__(self, index):
        """Posición 0 es el más antiguo; índices negativos cuentan desde el más nuevo."""
        if not isinstance(index, int):
            raise TypeError("El índice debe ser un entero.")
        if index < 0:
            index += self._size
        if not 0 <= index < self._size:
            raise IndexError("Índice fuera de rango.")
        return self._slots[(self._head + index) % self._capacity]

    def __iter__(self):
        for offset in range(self._size):
            yield self._slots[(self._head + offset) % self._capacity]

    def clear(self):
        self._slots = [None] * self._capacity
        self._head = 0
        self._size = 0

    def __repr__(self):
        return f"RecentItemsRing(capacity={self._capacity}, items={list(self)!r})"
