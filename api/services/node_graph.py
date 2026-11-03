"""Grafo en memoria de los nodos vecinos, construido a partir de ``NodeLink``.

Los vértices son los ``node_id`` y las aristas, los enlaces registrados. Se carga
una sola vez desde la base la primera vez que se necesita y después lo mantienen al
día las señales de ``api/cache_signals.py`` (alta y baja de enlaces), de modo que
consultar vecinos o recorrerlos no toca la base. Vive en el proceso: se pierde al
reiniciar y cada worker tiene su copia.
"""
import threading

from api.models import NodeLink
from api.services.locking import synchronized
from api.structures.adjacency_graph import AdjacencyGraph


class NodeGraph:
    def __init__(self):
        self._lock = threading.RLock()
        self._graph = None

    @synchronized
    def clear(self):
        """Descarta el grafo; se reconstruirá desde la base en el próximo uso."""
        self._graph = None

    @synchronized
    def is_loaded(self):
        return self._graph is not None

    def _loaded_graph(self):
        if self._graph is None:
            graph = AdjacencyGraph()
            links = NodeLink.objects.values_list("node_a__node_id", "node_b__node_id")
            for first, second in links:
                graph.add_edge(first, second)
            self._graph = graph
        return self._graph

    @synchronized
    def link_added(self, first, second):
        if self._graph is not None:
            self._graph.add_edge(first, second)

    @synchronized
    def link_removed(self, first, second):
        if self._graph is not None:
            self._graph.remove_edge(first, second)

    @synchronized
    def direct_neighbors(self, node_id):
        """Vecinos directos del nodo, en orden alfabético."""
        graph = self._loaded_graph()
        if node_id not in graph:
            return []
        return sorted(graph.neighbors(node_id))

    @synchronized
    def neighbors_within(self, node_id, max_hops):
        """``{vecino: saltos}`` de los nodos a ``max_hops`` saltos o menos (BFS)."""
        graph = self._loaded_graph()
        if node_id not in graph:
            return {}
        return graph.reachable_within(node_id, max_hops)

    @synchronized
    def linked_nodes(self):
        """Todos los nodos que tienen al menos un vecino."""
        return self._loaded_graph().vertices()


node_graph = NodeGraph()
