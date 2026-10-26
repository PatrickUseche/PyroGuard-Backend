from .bidirectional_chain import BidirectionalChain


class LeastRecentlyUsedCache:
    """Caché de capacidad fija que expulsa lo usado hace más tiempo (LRU).

    Combina dos estructuras: un diccionario que lleva de la clave a su nodo y
    una lista doblemente enlazada que guarda el orden de uso, con lo más reciente
    al frente. El diccionario permite encontrar el nodo en O(1) y la lista
    permite moverlo al frente o expulsar el del final también en O(1); con solo
    uno de los dos, una de esas operaciones costaría O(n).

    Complejidad (``k`` = capacidad):
        get(key) -- O(1), cuenta como uso
        put(key, value) -- O(1), expulsa el menos usado si está llena
        peek(key) / key in cache -- O(1), no cuentan como uso
        discard(key) -- O(1)
        keys() / items() -- O(n)
        espacio -- O(k)
    """

    def __init__(self, capacity):
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise ValueError("La capacidad debe ser un entero mayor o igual que 1.")
        self._capacity = capacity
        self._nodes = {}  # clave -> nodo de ``_order``
        self._order = BidirectionalChain()  # valores (clave, valor); frente = más reciente
        self._hits = 0
        self._misses = 0

    @property
    def capacity(self):
        return self._capacity

    @property
    def hits(self):
        return self._hits

    @property
    def misses(self):
        return self._misses

    def __len__(self):
        return len(self._nodes)

    def __contains__(self, key):
        return key in self._nodes

    def get(self, key, default=None):
        """Devuelve el valor y lo marca como el más reciente; ``default`` si no está."""
        node = self._nodes.get(key)
        if node is None:
            self._misses += 1
            return default
        self._hits += 1
        self._order.move_to_front(node)
        return node.value[1]

    def peek(self, key, default=None):
        """Devuelve el valor sin alterar el orden de uso ni las estadísticas."""
        node = self._nodes.get(key)
        return default if node is None else node.value[1]

    def put(self, key, value):
        """Guarda el valor como el más reciente; devuelve el par expulsado, si lo hubo."""
        node = self._nodes.get(key)
        if node is not None:
            node.value = (key, value)
            self._order.move_to_front(node)
            return None

        self._nodes[key] = self._order.push_front((key, value))
        if len(self._nodes) <= self._capacity:
            return None

        evicted_key, evicted_value = self._order.pop_back()
        del self._nodes[evicted_key]
        return evicted_key, evicted_value

    def discard(self, key):
        """Quita la clave si existe; devuelve si estaba."""
        node = self._nodes.pop(key, None)
        if node is None:
            return False
        self._order.remove(node)
        return True

    def keys(self):
        """Claves de la más reciente a la menos reciente."""
        return [key for key, _ in self._order]

    def items(self):
        """Pares (clave, valor) de la más reciente a la menos reciente."""
        return list(self._order)

    def clear(self):
        self._nodes.clear()
        self._order.clear()

    def reset_stats(self):
        self._hits = 0
        self._misses = 0

    def __repr__(self):
        return f"LeastRecentlyUsedCache(capacity={self._capacity}, items={self.items()!r})"
