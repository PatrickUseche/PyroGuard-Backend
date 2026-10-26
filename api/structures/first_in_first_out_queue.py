class _QueueNode:
    __slots__ = ("value", "next")

    def __init__(self, value):
        self.value = value
        self.next = None


class FirstInFirstOutQueue:
    """Cola FIFO (el primero en entrar es el primero en salir) con nodos enlazados.

    Guarda referencias al primer y al último nodo. Encolar enlaza detrás del
    último y desencolar suelta el primero, así que ninguna de las dos recorre la
    cola ni desplaza elementos, a diferencia de ``list.pop(0)``, que es O(n).

    Complejidad (``n`` = elementos):
        enqueue(item) -- O(1) en el peor caso
        dequeue() -- O(1) en el peor caso
        peek() / len() / is_empty() -- O(1)
        FirstInFirstOutQueue(items) / iter(cola) / clear() -- O(n)
        espacio -- O(n), un nodo por elemento
    """

    def __init__(self, items=()):
        self._first = None
        self._last = None
        self._size = 0
        for item in items:
            self.enqueue(item)

    def __len__(self):
        return self._size

    def is_empty(self):
        return self._size == 0

    def enqueue(self, item):
        node = _QueueNode(item)
        if self._last is None:
            self._first = node
        else:
            self._last.next = node
        self._last = node
        self._size += 1

    def dequeue(self):
        if self._first is None:
            raise IndexError("La cola está vacía.")
        node = self._first
        self._first = node.next
        if self._first is None:
            self._last = None
        self._size -= 1
        return node.value

    def peek(self):
        """Devuelve el próximo en salir sin sacarlo."""
        if self._first is None:
            raise IndexError("La cola está vacía.")
        return self._first.value

    def __iter__(self):
        """Recorre del próximo en salir al último en entrar, sin consumir la cola."""
        node = self._first
        while node is not None:
            yield node.value
            node = node.next

    def clear(self):
        self._first = None
        self._last = None
        self._size = 0

    def __repr__(self):
        return f"FirstInFirstOutQueue({list(self)!r})"
