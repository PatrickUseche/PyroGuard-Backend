"""Pruebas del candado que protege el estado en memoria compartido entre peticiones."""
import threading
from datetime import datetime, timezone as dt_timezone

from django.test import SimpleTestCase, TransactionTestCase, override_settings

from .models import Node, SensorReading
from .services.dashboard_cache import DashboardSummaryCache, dashboard_cache
from .services.duplicate_readings import DuplicateReadingDetector, duplicate_readings
from .services.live_readings import LiveReadingsStore, live_readings
from .services.locking import synchronized
from .services.node_graph import NodeGraph, node_graph
from .services.node_search import NodeSearchIndex, node_search_index
from .services.node_status_cache import NodeStatusCache, node_status_cache


STATEFUL_SERVICES = (
    (LiveReadingsStore, live_readings),
    (NodeStatusCache, node_status_cache),
    (DashboardSummaryCache, dashboard_cache),
    (DuplicateReadingDetector, duplicate_readings),
    (NodeSearchIndex, node_search_index),
    (NodeGraph, node_graph),
)


class SynchronizedDecoratorTests(SimpleTestCase):
    def test_the_method_runs_with_the_lock_held(self):
        class Counter:
            def __init__(self):
                self._lock = threading.RLock()
                self.held = []

            @synchronized
            def check(self):
                self.held.append(self._lock._is_owned())
                return "ok"

        counter = Counter()

        self.assertEqual(counter.check(), "ok")
        self.assertEqual(counter.held, [True])
        self.assertFalse(counter._lock._is_owned())

    def test_the_lock_is_released_when_the_method_fails(self):
        class Broken:
            def __init__(self):
                self._lock = threading.RLock()

            @synchronized
            def fail(self):
                raise RuntimeError("fallo")

        broken = Broken()

        with self.assertRaises(RuntimeError):
            broken.fail()

        self.assertFalse(broken._lock._is_owned())

    def test_a_method_can_call_another_synchronized_method(self):
        class Nested:
            def __init__(self):
                self._lock = threading.RLock()

            @synchronized
            def outer(self):
                return self.inner() + 1

            @synchronized
            def inner(self):
                return 1

        self.assertEqual(Nested().outer(), 2)

    def test_it_keeps_the_name_and_docstring(self):
        class Documented:
            def __init__(self):
                self._lock = threading.RLock()

            @synchronized
            def described(self):
                """Texto."""

        self.assertEqual(Documented.described.__name__, "described")
        self.assertEqual(Documented.described.__doc__, "Texto.")

    def test_only_one_thread_at_a_time_runs_inside(self):
        class Probe:
            def __init__(self):
                self._lock = threading.RLock()
                self.inside = 0
                self.max_inside = 0

            @synchronized
            def work(self):
                self.inside += 1
                self.max_inside = max(self.max_inside, self.inside)
                for _ in range(200):
                    pass
                self.inside -= 1

        probe = Probe()
        threads = [threading.Thread(target=lambda: [probe.work() for _ in range(200)]) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(probe.max_inside, 1)


class StatefulServicesAreProtectedTests(SimpleTestCase):
    def test_every_stateful_service_has_its_own_reentrant_lock(self):
        locks = []
        for service_class, _ in STATEFUL_SERVICES:
            instance = service_class()
            with self.subTest(service=service_class.__name__):
                self.assertTrue(hasattr(instance._lock, "acquire"))
                locks.append(instance._lock)
        self.assertEqual(len({id(lock) for lock in locks}), len(locks))

    def test_every_public_method_is_synchronized(self):
        for service_class, _ in STATEFUL_SERVICES:
            for name, member in vars(service_class).items():
                if name.startswith("_"):
                    continue
                function = member.fget if isinstance(member, property) else member
                if not callable(function):
                    continue
                with self.subTest(service=service_class.__name__, method=name):
                    self.assertTrue(
                        hasattr(function, "__wrapped__"),
                        f"{service_class.__name__}.{name} no está protegido con @synchronized",
                    )


@override_settings(
    RECENT_READINGS_PER_NODE=10,
    TEMPERATURE_WINDOW_SIZE=10,
    NODE_STATUS_CACHE_SIZE=5,
    DUPLICATE_FILTER_CAPACITY=1000,
    DASHBOARD_CACHE_SECONDS=60,
)
class ConcurrentUseTests(TransactionTestCase):
    """Varios hilos usan a la vez el mismo estado, como haría gunicorn con hilos."""

    def setUp(self):
        for state in (live_readings, node_status_cache, dashboard_cache, duplicate_readings,
                      node_search_index, node_graph):
            state.clear()
            self.addCleanup(state.clear)

    def run_threads(self, target, count=8):
        errors = []

        def guarded(index):
            try:
                target(index)
            except Exception as error:  # noqa: BLE001 - se informa al final
                errors.append(error)

        threads = [threading.Thread(target=guarded, args=(index,)) for index in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return errors

    def test_the_status_cache_never_exceeds_its_capacity_under_concurrency(self):
        def work(index):
            for number in range(300):
                key = f"N{(index * 31 + number) % 20}"
                node_status_cache.put(key, {"n": number})
                node_status_cache.get(key)
                if number % 7 == 0:
                    node_status_cache.invalidate(key)

        errors = self.run_threads(work)

        self.assertEqual(errors, [])
        self.assertLessEqual(node_status_cache.stats["size"], 5)

    def test_the_duplicate_filter_counts_every_distinct_reading_once(self):
        node = Node.objects.create(node_id="NODE-1")
        moment = datetime(2026, 10, 30, 12, 0, tzinfo=dt_timezone.utc)

        def work(index):
            for number in range(50):
                duplicate_readings.remember(node.node_id, moment.replace(second=number % 60, minute=index))

        errors = self.run_threads(work)

        self.assertEqual(errors, [])
        self.assertEqual(len(duplicate_readings._filter), 8 * 50)

    def test_the_node_graph_stays_consistent_while_links_are_added(self):
        for number in range(12):
            Node.objects.create(node_id=f"N{number:02d}")
        node_graph.direct_neighbors("N00")  # carga el grafo (vacío) desde la base

        def work(index):
            # Solo memoria: la concurrencia de escrituras en la base es cosa de la base.
            for other in range(index + 1, 12):
                node_graph.link_added(f"N{index:02d}", f"N{other:02d}")
                node_graph.direct_neighbors(f"N{index:02d}")

        errors = self.run_threads(work, count=11)

        self.assertEqual(errors, [])
        everyone_else = {f"N{number:02d}" for number in range(1, 12)}
        self.assertEqual(set(node_graph.direct_neighbors("N00")), everyone_else)
        self.assertEqual(len(node_graph.neighbors_within("N05", 1)), 11)

    def test_recording_readings_from_many_threads_keeps_the_ring_bounded(self):
        node = Node.objects.create(node_id="NODE-1")
        live_readings.recent(node)
        live_readings.temperature_window(node.node_id)  # ambos se cargan antes de lanzar hilos

        def work(index):
            for number in range(40):
                reading = SensorReading(node=node, temperature=20 + number, humidity=40, smoke=1, flame=False)
                live_readings.record(reading)
                live_readings.temperature_window(node.node_id)

        errors = self.run_threads(work)

        self.assertEqual(errors, [])
        self.assertEqual(len(live_readings.recent(node)), 10)
        window = live_readings.temperature_window(node.node_id)
        self.assertEqual(window["readings"], 10)
