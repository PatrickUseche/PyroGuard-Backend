"""`repr` de las estructuras propias: muestran capacidad y contenido en orden (útil al depurar)."""
from django.test import SimpleTestCase

from .structures.bidirectional_chain import BidirectionalChain
from .structures.first_in_first_out_queue import FirstInFirstOutQueue
from .structures.least_recently_used_cache import LeastRecentlyUsedCache
from .structures.recent_items_ring import RecentItemsRing


class StructureReprTests(SimpleTestCase):
    def test_ring_shows_capacity_and_items_from_oldest_to_newest(self):
        ring = RecentItemsRing(2)
        for item in (1, 2, 3):
            ring.append(item)
        self.assertEqual(repr(ring), "RecentItemsRing(capacity=2, items=[2, 3])")

    def test_queue_shows_items_in_arrival_order(self):
        queue = FirstInFirstOutQueue()
        queue.enqueue("a")
        queue.enqueue("b")
        self.assertEqual(repr(queue), "FirstInFirstOutQueue(['a', 'b'])")

    def test_lru_shows_capacity_and_items(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("x", 1)
        self.assertEqual(repr(cache), f"LeastRecentlyUsedCache(capacity=2, items={cache.items()!r})")

    def test_chain_and_its_links_show_their_values(self):
        chain = BidirectionalChain()
        chain.push_back(1)
        chain.push_back(2)
        self.assertEqual(repr(chain), "BidirectionalChain([1, 2])")
        self.assertEqual(repr(chain.front_node()), "ChainLink(1)")
