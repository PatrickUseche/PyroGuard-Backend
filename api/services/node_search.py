"""Índice en memoria de los ``node_id`` para buscarlos por prefijo.

Un ``PrefixTrie`` guarda los identificadores de los nodos. Se carga una sola vez
desde la base la primera vez que se busca y después lo mantienen al día las
señales de ``api/cache_signals.py`` (alta y baja de nodos), así que buscar cuesta
lo que mide el prefijo y no consulta la base.

La búsqueda ignora mayúsculas. Como el árbol también las ignora, dos nodos cuyos
identificadores solo difieran en mayúsculas comparten una entrada (se conserva el
primero); en la práctica los ``node_id`` no se distinguen así. El índice vive en
el proceso: se pierde al reiniciar y cada worker tiene el suyo.
"""
import threading

from api.models import Node
from api.services.locking import synchronized
from api.structures.prefix_trie import PrefixTrie


class NodeSearchIndex:
    def __init__(self):
        self._lock = threading.RLock()
        self._trie = None

    @synchronized
    def clear(self):
        self._trie = None

    @synchronized
    def is_loaded(self):
        return self._trie is not None

    def _loaded_trie(self):
        if self._trie is None:
            trie = PrefixTrie()
            for node_id in Node.objects.values_list("node_id", flat=True):
                trie.insert(node_id)
            self._trie = trie
        return self._trie

    @synchronized
    def search(self, prefix, limit=None):
        """Identificadores que empiezan por ``prefix``, en orden alfabético."""
        return self._loaded_trie().with_prefix(prefix, limit=limit)

    @synchronized
    def node_added(self, node_id):
        if self._trie is not None:
            self._trie.insert(node_id)

    @synchronized
    def node_removed(self, node_id):
        if self._trie is not None:
            self._trie.delete(node_id)


node_search_index = NodeSearchIndex()
