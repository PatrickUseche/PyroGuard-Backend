class PriorityMinHeap:
    """Montículo binario mínimo con función de prioridad configurable.

    Sale primero el elemento con menor prioridad. La prioridad se calcula con
    ``priority(item)`` una sola vez, al insertar; si no se pasa función, el propio
    elemento es su prioridad. Para obtener el mayor primero basta con devolver el
    valor negado (``priority=lambda x: -x.score``). Los empates salen en el orden
    de inserción (se desempata con un contador), así que el montículo es estable.

    Se guarda en una lista donde los hijos de la posición ``i`` están en ``2i + 1``
    y ``2i + 2``.

    Complejidad (``n`` = elementos guardados):
        push(item) -- O(log n)
        pop() -- O(log n)
        peek() / len() / is_empty() -- O(1)
        PriorityMinHeap.from_items(items) -- O(n), construcción por «heapify»
        PriorityMinHeap.smallest(items, k) -- O(n + k log n)
        espacio -- O(n)
    """

    def __init__(self, priority=None):
        if priority is not None and not callable(priority):
            raise TypeError("La prioridad debe ser una función o None.")
        self._priority = priority if priority is not None else (lambda item: item)
        self._entries = []  # tuplas (prioridad, orden de llegada, elemento)
        self._arrivals = 0

    @classmethod
    def from_items(cls, items, priority=None):
        """Construye el montículo de golpe con ``heapify``, en O(n)."""
        heap = cls(priority)
        for item in items:
            heap._entries.append((heap._priority(item), heap._arrivals, item))
            heap._arrivals += 1
        for index in range(len(heap._entries) // 2 - 1, -1, -1):
            heap._sift_down(index)
        return heap

    @classmethod
    def smallest(cls, items, k, priority=None):
        """Devuelve los ``k`` elementos de menor prioridad, de menor a mayor."""
        if not isinstance(k, int) or isinstance(k, bool) or k < 0:
            raise ValueError("k debe ser un entero mayor o igual que 0.")
        heap = cls.from_items(items, priority)
        return [heap.pop() for _ in range(min(k, len(heap)))]

    def __len__(self):
        return len(self._entries)

    def is_empty(self):
        return not self._entries

    def push(self, item):
        self._entries.append((self._priority(item), self._arrivals, item))
        self._arrivals += 1
        self._sift_up(len(self._entries) - 1)

    def peek(self):
        if not self._entries:
            raise IndexError("El montículo está vacío.")
        return self._entries[0][2]

    def pop(self):
        if not self._entries:
            raise IndexError("El montículo está vacío.")
        top = self._entries[0]
        last = self._entries.pop()
        if self._entries:
            self._entries[0] = last
            self._sift_down(0)
        return top[2]

    def _sift_up(self, index):
        entries = self._entries
        entry = entries[index]
        while index > 0:
            parent = (index - 1) // 2
            if entries[parent][:2] <= entry[:2]:
                break
            entries[index] = entries[parent]
            index = parent
        entries[index] = entry

    def _sift_down(self, index):
        entries = self._entries
        size = len(entries)
        entry = entries[index]
        while True:
            child = 2 * index + 1
            if child >= size:
                break
            if child + 1 < size and entries[child + 1][:2] < entries[child][:2]:
                child += 1
            if entry[:2] <= entries[child][:2]:
                break
            entries[index] = entries[child]
            index = child
        entries[index] = entry
