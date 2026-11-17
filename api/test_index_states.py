"""Estado del índice de búsqueda por prefijo y estadísticas de la caché del dashboard."""
from django.test import TestCase, override_settings

from .models import Node
from .services.dashboard_cache import DashboardSummaryCache
from .services.node_search import NodeSearchIndex


class NodeSearchIndexStateTests(TestCase):
    def test_the_index_loads_on_the_first_search_and_clear_unloads_it(self):
        Node.objects.create(node_id="ZONA-1")
        index = NodeSearchIndex()
        self.assertFalse(index.is_loaded())

        self.assertEqual(index.search("ZONA"), ["ZONA-1"])
        self.assertTrue(index.is_loaded())

        index.clear()
        self.assertFalse(index.is_loaded())


@override_settings(DASHBOARD_CACHE_SECONDS=30)
class DashboardCacheStatsTests(TestCase):
    def test_stats_count_hits_misses_and_size(self):
        cache = DashboardSummaryCache(clock=lambda: 0.0)
        self.assertIsNone(cache.get())
        cache.put({"nodes": 1})
        self.assertEqual(cache.get(), {"nodes": 1})

        self.assertEqual(cache.stats, {"hits": 1, "misses": 1, "size": 1})
        cache.invalidate()
        self.assertEqual(cache.stats["size"], 0)
