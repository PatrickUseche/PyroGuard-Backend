class DisjointSetUnion:
    """Conjuntos disjuntos (Union-Find) con compresión de caminos y unión por rango.

    Agrupa elementos en conjuntos que no se solapan y responde rápido si dos
    elementos están en el mismo grupo. Sirve para formar zonas con los nodos
    conectados entre sí. Los elementos se registran con ``add`` (o al unirlos) y
    pueden ser cualquier valor hashable.

    Cada conjunto es un árbol cuya raíz lo representa. La unión por rango cuelga el
    árbol más bajo bajo el más alto, y la compresión de caminos apunta cada
    elemento recorrido directamente a la raíz.

    Complejidad (``n`` = elementos, ``α`` = inversa de Ackermann, menor que 5 para
    cualquier ``n`` práctico):
        add(x) -- O(1)
        find(x) / connected(a, b) / union(a, b) -- O(α(n)) amortizado
        groups() -- O(n α(n))
        len() / group_count() -- O(1)
        espacio -- O(n)
    """

    def __init__(self, items=()):
        self._parent = {}
        self._rank = {}
        self._groups = 0
        for item in items:
            self.add(item)

    def __len__(self):
        return len(self._parent)

    def __contains__(self, item):
        return item in self._parent

    def group_count(self):
        return self._groups

    def add(self, item):
        """Registra ``item`` como su propio conjunto; devuelve ``False`` si ya estaba."""
        if item in self._parent:
            return False
        self._parent[item] = item
        self._rank[item] = 0
        self._groups += 1
        return True

    def find(self, item):
        """Devuelve el representante del conjunto de ``item`` y comprime el camino."""
        if item not in self._parent:
            raise KeyError(item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, first, second):
        """Une los conjuntos de ambos elementos (los crea si faltan).

        Devuelve ``True`` si estaban separados y ``False`` si ya eran el mismo.
        """
        self.add(first)
        self.add(second)
        root_first = self.find(first)
        root_second = self.find(second)
        if root_first == root_second:
            return False
        if self._rank[root_first] < self._rank[root_second]:
            root_first, root_second = root_second, root_first
        self._parent[root_second] = root_first
        if self._rank[root_first] == self._rank[root_second]:
            self._rank[root_first] += 1
        self._groups -= 1
        return True

    def connected(self, first, second):
        return self.find(first) == self.find(second)

    def groups(self):
        """Devuelve la lista de conjuntos, cada uno como lista en orden de registro."""
        by_root = {}
        for item in self._parent:
            by_root.setdefault(self.find(item), []).append(item)
        return list(by_root.values())
