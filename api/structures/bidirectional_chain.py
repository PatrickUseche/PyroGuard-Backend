class ChainLink:
    """Nodo de ``BidirectionalChain``; ``value`` es lo que guarda el usuario."""

    __slots__ = ("value", "prev", "next", "_owner")

    def __init__(self, value):
        self.value = value
        self.prev = None
        self.next = None
        self._owner = None

    def __repr__(self):
        return f"ChainLink({self.value!r})"


class BidirectionalChain:
    """Lista doblemente enlazada con nodos centinela en ambos extremos.

    Los centinelas evitan los casos especiales de lista vacía o de un solo
    elemento. Las operaciones que reciben un nodo (``remove``, ``move_to_front``,
    ``move_to_back``) no buscan: usan sus enlaces, y por eso son O(1). Esa es la
    razón de ser de la estructura frente a un arreglo, donde quitar del medio es
    O(n).

    Complejidad (``n`` = elementos):
        push_front / push_back -- O(1)
        pop_front / pop_back -- O(1)
        remove(node) / move_to_front(node) / move_to_back(node) -- O(1)
        front() / back() / front_node() / back_node() / len() -- O(1)
        iter(lista) / reversed() -- O(n)
        clear() -- O(n), porque invalida cada nodo para que no se reutilice
        espacio -- O(n), dos enlaces por nodo
    """

    def __init__(self):
        self._head = ChainLink(None)  # centinela antes del primero
        self._tail = ChainLink(None)  # centinela después del último
        self._head.next = self._tail
        self._tail.prev = self._head
        self._size = 0

    def __len__(self):
        return self._size

    def is_empty(self):
        return self._size == 0

    def _link_after(self, previous, node):
        node.prev = previous
        node.next = previous.next
        previous.next.prev = node
        previous.next = node
        node._owner = self
        self._size += 1

    def _unlink(self, node):
        node.prev.next = node.next
        node.next.prev = node.prev
        node.prev = None
        node.next = None
        node._owner = None
        self._size -= 1

    def _check_owned(self, node):
        if not isinstance(node, ChainLink) or node._owner is not self:
            raise ValueError("El nodo no pertenece a esta lista.")

    def push_front(self, value):
        """Inserta al inicio y devuelve el nodo creado."""
        node = ChainLink(value)
        self._link_after(self._head, node)
        return node

    def push_back(self, value):
        """Inserta al final y devuelve el nodo creado."""
        node = ChainLink(value)
        self._link_after(self._tail.prev, node)
        return node

    def pop_front(self):
        if self._size == 0:
            raise IndexError("La lista está vacía.")
        node = self._head.next
        self._unlink(node)
        return node.value

    def pop_back(self):
        if self._size == 0:
            raise IndexError("La lista está vacía.")
        node = self._tail.prev
        self._unlink(node)
        return node.value

    def front(self):
        if self._size == 0:
            raise IndexError("La lista está vacía.")
        return self._head.next.value

    def back(self):
        if self._size == 0:
            raise IndexError("La lista está vacía.")
        return self._tail.prev.value

    def front_node(self):
        if self._size == 0:
            raise IndexError("La lista está vacía.")
        return self._head.next

    def back_node(self):
        if self._size == 0:
            raise IndexError("La lista está vacía.")
        return self._tail.prev

    def remove(self, node):
        """Quita un nodo de la lista y devuelve su valor."""
        self._check_owned(node)
        self._unlink(node)
        return node.value

    def move_to_front(self, node):
        self._check_owned(node)
        if self._head.next is node:
            return
        self._unlink(node)
        self._link_after(self._head, node)

    def move_to_back(self, node):
        self._check_owned(node)
        if self._tail.prev is node:
            return
        self._unlink(node)
        self._link_after(self._tail.prev, node)

    def __iter__(self):
        """Recorre los valores del primero al último."""
        node = self._head.next
        while node is not self._tail:
            yield node.value
            node = node.next

    def reversed(self):
        """Recorre los valores del último al primero."""
        node = self._tail.prev
        while node is not self._head:
            yield node.value
            node = node.prev

    def clear(self):
        node = self._head.next
        while node is not self._tail:
            following = node.next
            node.prev = None
            node.next = None
            node._owner = None
            node = following
        self._head.next = self._tail
        self._tail.prev = self._head
        self._size = 0

    def __repr__(self):
        return f"BidirectionalChain({list(self)!r})"
