from .first_in_first_out_queue import FirstInFirstOutQueue


class AdjacencyGraph:
    """Grafo no dirigido guardado como lista de adyacencia (diccionario de conjuntos).

    Sirve para modelar qué nodos de sensores son vecinos. Los vértices pueden ser
    cualquier valor hashable. No admite lazos (un vértice unido a sí mismo) y unir
    dos vértices que ya están unidos no hace nada.

    Complejidad (``V`` = vértices, ``E`` = aristas):
        add_vertex(v) / add_edge(a, b) / has_edge(a, b) -- O(1) esperado
        neighbors(v) -- O(grado de v), devuelve una copia
        remove_edge(a, b) -- O(1) esperado
        remove_vertex(v) -- O(grado de v)
        edge_count() -- O(V)
        reachable_within(start, max_hops) -- O(V + E) en el peor caso (BFS)
        espacio -- O(V + E)
    """

    def __init__(self):
        self._adjacent = {}

    def __len__(self):
        return len(self._adjacent)

    def __contains__(self, vertex):
        return vertex in self._adjacent

    def vertices(self):
        return list(self._adjacent)

    def edge_count(self):
        return sum(len(neighbors) for neighbors in self._adjacent.values()) // 2

    def add_vertex(self, vertex):
        self._adjacent.setdefault(vertex, set())

    def add_edge(self, first, second):
        if first == second:
            raise ValueError("Un vértice no puede ser vecino de sí mismo.")
        self.add_vertex(first)
        self.add_vertex(second)
        self._adjacent[first].add(second)
        self._adjacent[second].add(first)

    def has_edge(self, first, second):
        return second in self._adjacent.get(first, ())

    def remove_edge(self, first, second):
        """Quita la arista; devuelve ``True`` si existía."""
        if not self.has_edge(first, second):
            return False
        self._adjacent[first].discard(second)
        self._adjacent[second].discard(first)
        return True

    def remove_vertex(self, vertex):
        """Quita el vértice y todas sus aristas; devuelve ``True`` si existía."""
        if vertex not in self._adjacent:
            return False
        for other in self._adjacent.pop(vertex):
            self._adjacent[other].discard(vertex)
        return True

    def neighbors(self, vertex):
        if vertex not in self._adjacent:
            raise KeyError(vertex)
        return set(self._adjacent[vertex])

    def reachable_within(self, start, max_hops=None):
        """Recorrido en anchura (BFS) desde ``start``.

        Devuelve un diccionario ``{vértice: saltos}`` con los vértices alcanzables
        en ``max_hops`` saltos o menos (sin límite si es ``None``), sin incluir
        ``start``, en orden de cercanía. Cada vértice se visita una sola vez, así
        que los ciclos no provocan bucles.
        """
        if start not in self._adjacent:
            raise KeyError(start)
        if max_hops is not None and (
            not isinstance(max_hops, int) or isinstance(max_hops, bool) or max_hops < 0
        ):
            raise ValueError("max_hops debe ser un entero mayor o igual que 0.")

        hops = {start: 0}
        pending = FirstInFirstOutQueue([start])
        while not pending.is_empty():
            current = pending.dequeue()
            if max_hops is not None and hops[current] >= max_hops:
                continue
            for neighbor in self._adjacent[current]:
                if neighbor not in hops:
                    hops[neighbor] = hops[current] + 1
                    pending.enqueue(neighbor)
        del hops[start]
        return hops
