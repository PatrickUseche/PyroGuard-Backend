import random
from collections import OrderedDict

from django.test import SimpleTestCase

from .structures.bidirectional_chain import BidirectionalChain, ChainLink
from .structures.first_in_first_out_queue import FirstInFirstOutQueue
from .structures.least_recently_used_cache import LeastRecentlyUsedCache
from .structures.prefix_trie import PrefixTrie
from .structures.priority_min_heap import PriorityMinHeap
from .structures.recent_items_ring import RecentItemsRing
from .structures.rolling_extremes_window import RollingExtremesWindow


class RecentItemsRingTests(SimpleTestCase):
    def test_capacity_must_be_a_positive_integer(self):
        for capacity in (0, -1, 1.5, "3", None, True):
            with self.subTest(capacity=capacity):
                with self.assertRaises(ValueError):
                    RecentItemsRing(capacity)

    def test_new_buffer_is_empty(self):
        buffer = RecentItemsRing(3)

        self.assertEqual(len(buffer), 0)
        self.assertTrue(buffer.is_empty())
        self.assertFalse(buffer.is_full())
        self.assertEqual(list(buffer), [])
        self.assertEqual(buffer.capacity, 3)

    def test_empty_buffer_has_no_oldest_or_newest(self):
        buffer = RecentItemsRing(2)

        with self.assertRaises(IndexError):
            buffer.oldest()
        with self.assertRaises(IndexError):
            buffer.newest()
        with self.assertRaises(IndexError):
            buffer[0]

    def test_items_are_kept_in_insertion_order_until_full(self):
        buffer = RecentItemsRing(3)
        for value in (1, 2):
            self.assertIs(buffer.append(value), RecentItemsRing.NOTHING_EVICTED)

        self.assertEqual(list(buffer), [1, 2])
        self.assertEqual(len(buffer), 2)
        self.assertFalse(buffer.is_full())

        buffer.append(3)
        self.assertTrue(buffer.is_full())
        self.assertEqual(list(buffer), [1, 2, 3])

    def test_full_buffer_overwrites_the_oldest_and_returns_it(self):
        buffer = RecentItemsRing(3)
        for value in (1, 2, 3):
            buffer.append(value)

        self.assertEqual(buffer.append(4), 1)
        self.assertEqual(buffer.append(5), 2)

        self.assertEqual(list(buffer), [3, 4, 5])
        self.assertEqual(len(buffer), 3)

    def test_oldest_and_newest_follow_the_overwrites(self):
        buffer = RecentItemsRing(3)
        for value in range(1, 8):
            buffer.append(value)

        self.assertEqual(buffer.oldest(), 5)
        self.assertEqual(buffer.newest(), 7)

    def test_indexing_counts_from_the_oldest_and_supports_negatives(self):
        buffer = RecentItemsRing(3)
        for value in range(10, 15):
            buffer.append(value)

        self.assertEqual([buffer[0], buffer[1], buffer[2]], [12, 13, 14])
        self.assertEqual(buffer[-1], 14)
        self.assertEqual(buffer[-3], 12)

    def test_index_out_of_range_or_wrong_type_is_rejected(self):
        buffer = RecentItemsRing(3)
        buffer.append("a")

        for index in (1, 3, -2, 99):
            with self.subTest(index=index):
                with self.assertRaises(IndexError):
                    buffer[index]
        with self.assertRaises(TypeError):
            buffer["0"]

    def test_capacity_one_always_keeps_the_last_item(self):
        buffer = RecentItemsRing(1)

        self.assertIs(buffer.append("a"), RecentItemsRing.NOTHING_EVICTED)
        self.assertEqual(buffer.append("b"), "a")
        self.assertEqual(buffer.append("c"), "b")

        self.assertEqual(list(buffer), ["c"])
        self.assertEqual(buffer.oldest(), buffer.newest())

    def test_wraps_around_many_times_keeping_the_last_k_items(self):
        buffer = RecentItemsRing(4)
        for value in range(1000):
            buffer.append(value)

        self.assertEqual(list(buffer), [996, 997, 998, 999])

    def test_none_is_a_valid_item(self):
        buffer = RecentItemsRing(2)
        buffer.append(None)
        buffer.append(None)

        self.assertEqual(len(buffer), 2)
        self.assertEqual(list(buffer), [None, None])

    def test_evicting_a_stored_none_is_distinguishable_from_evicting_nothing(self):
        buffer = RecentItemsRing(2)

        nothing_yet = [buffer.append(None), buffer.append("x")]
        evicted_none = buffer.append("y")

        self.assertIs(nothing_yet[0], RecentItemsRing.NOTHING_EVICTED)
        self.assertIs(nothing_yet[1], RecentItemsRing.NOTHING_EVICTED)
        self.assertIsNone(evicted_none)
        self.assertIsNot(evicted_none, RecentItemsRing.NOTHING_EVICTED)

    def test_nothing_evicted_marker_is_falsy_and_readable(self):
        marker = RecentItemsRing.NOTHING_EVICTED

        self.assertFalse(marker)
        self.assertEqual(repr(marker), "NOTHING_EVICTED")
        self.assertIs(RecentItemsRing(1).append("a"), marker)

    def test_clear_empties_the_buffer_and_it_can_be_reused(self):
        buffer = RecentItemsRing(3)
        for value in range(5):
            buffer.append(value)

        buffer.clear()

        self.assertTrue(buffer.is_empty())
        self.assertEqual(list(buffer), [])
        buffer.append("x")
        self.assertEqual(list(buffer), ["x"])
        self.assertEqual(buffer.oldest(), "x")

    def test_iteration_does_not_consume_the_buffer(self):
        buffer = RecentItemsRing(3)
        for value in (1, 2, 3):
            buffer.append(value)

        self.assertEqual(list(buffer), list(buffer))
        self.assertEqual(len(buffer), 3)

    def test_matches_a_plain_list_of_the_last_k_items(self):
        capacity = 5
        buffer = RecentItemsRing(capacity)
        reference = []
        for value in range(37):
            buffer.append(value)
            reference.append(value)
            reference = reference[-capacity:]

            self.assertEqual(list(buffer), reference)


def brute_force_extremes(values, size):
    window = values[-size:]
    return max(window), min(window)


class RollingExtremesWindowTests(SimpleTestCase):
    def test_size_must_be_a_positive_integer(self):
        for size in (0, -3, 2.5, "4", None, True):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    RollingExtremesWindow(size)

    def test_empty_window_has_no_extremes(self):
        window = RollingExtremesWindow(3)

        self.assertTrue(window.is_empty())
        self.assertEqual(len(window), 0)
        with self.assertRaises(ValueError):
            window.maximum
        with self.assertRaises(ValueError):
            window.minimum

    def test_only_numbers_are_accepted(self):
        window = RollingExtremesWindow(3)

        for value in ("5", None, True, [1], (2,)):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    window.push(value)
        with self.assertRaises(ValueError):
            window.push(float("nan"))
        self.assertTrue(window.is_empty())

    def test_single_value_is_both_extremes(self):
        window = RollingExtremesWindow(3)
        window.push(7)

        self.assertEqual((window.maximum, window.minimum), (7, 7))
        self.assertEqual(len(window), 1)
        self.assertFalse(window.is_full())

    def test_old_extreme_leaves_when_it_slides_out(self):
        window = RollingExtremesWindow(3)
        for value in (10, 1, 2):
            window.push(value)
        self.assertEqual((window.maximum, window.minimum), (10, 1))

        window.push(3)  # sale el 10
        self.assertEqual((window.maximum, window.minimum), (3, 1))

        window.push(4)  # sale el 1
        self.assertEqual((window.maximum, window.minimum), (4, 2))

    def test_window_of_one_tracks_the_last_value(self):
        window = RollingExtremesWindow(1)
        for value in (5, 3, 9, -2):
            window.push(value)

            self.assertEqual((window.maximum, window.minimum), (value, value))

    def test_repeated_values_do_not_expire_early(self):
        window = RollingExtremesWindow(3)
        for value in (5, 5, 5):
            window.push(value)
        window.push(1)  # sale un 5, quedan dos
        self.assertEqual(window.maximum, 5)

        window.push(1)  # queda un 5
        self.assertEqual(window.maximum, 5)

        window.push(1)  # ya no queda ningún 5
        self.assertEqual((window.maximum, window.minimum), (1, 1))

    def test_monotonic_sequences(self):
        increasing = RollingExtremesWindow(4)
        decreasing = RollingExtremesWindow(4)
        for value in range(20):
            increasing.push(value)
            decreasing.push(-value)

        self.assertEqual((increasing.maximum, increasing.minimum), (19, 16))
        self.assertEqual((decreasing.maximum, decreasing.minimum), (-16, -19))

    def test_floats_and_negatives(self):
        window = RollingExtremesWindow(2)
        for value in (-1.5, 2.25, -3.0):
            window.push(value)

        self.assertEqual((window.maximum, window.minimum), (2.25, -3.0))

    def test_len_and_is_full_follow_the_window(self):
        window = RollingExtremesWindow(3)
        sizes = []
        for value in range(5):
            window.push(value)
            sizes.append((len(window), window.is_full()))

        self.assertEqual(
            sizes, [(1, False), (2, False), (3, True), (3, True), (3, True)]
        )

    def test_matches_brute_force_on_random_data(self):
        generator = random.Random(2026)
        for size in (1, 2, 3, 5, 17, 100):
            with self.subTest(size=size):
                window = RollingExtremesWindow(size)
                values = []
                for _ in range(600):
                    value = generator.randint(-50, 50)  # con muchos repetidos
                    values.append(value)
                    window.push(value)

                    self.assertEqual(
                        (window.maximum, window.minimum),
                        brute_force_extremes(values, size),
                    )

    def test_matches_brute_force_with_floats(self):
        generator = random.Random(7)
        window = RollingExtremesWindow(8)
        values = []
        for _ in range(300):
            value = round(generator.uniform(-40, 120), 2)
            values.append(value)
            window.push(value)

            self.assertEqual(
                (window.maximum, window.minimum), brute_force_extremes(values, 8)
            )

    def test_long_runs_keep_working_after_the_internal_compaction(self):
        window = RollingExtremesWindow(200)
        values = []
        for index in range(5000):
            value = (index * 37) % 101
            values.append(value)
            window.push(value)

        self.assertEqual(
            (window.maximum, window.minimum), brute_force_extremes(values, 200)
        )


class BidirectionalChainTests(SimpleTestCase):
    def build(self, *values):
        linked = BidirectionalChain()
        nodes = [linked.push_back(value) for value in values]
        return linked, nodes

    def forward_and_backward(self, linked):
        return list(linked), list(linked.reversed())

    def test_new_list_is_empty(self):
        linked = BidirectionalChain()

        self.assertEqual(len(linked), 0)
        self.assertTrue(linked.is_empty())
        self.assertEqual(list(linked), [])
        self.assertEqual(list(linked.reversed()), [])

    def test_empty_list_rejects_reads_and_pops(self):
        linked = BidirectionalChain()

        for operation in (
            linked.pop_front,
            linked.pop_back,
            linked.front,
            linked.back,
            linked.front_node,
            linked.back_node,
        ):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(IndexError):
                    operation()

    def test_push_front_and_push_back_keep_order_in_both_directions(self):
        linked = BidirectionalChain()
        linked.push_back(2)
        linked.push_back(3)
        linked.push_front(1)
        linked.push_front(0)

        forward, backward = self.forward_and_backward(linked)
        self.assertEqual(forward, [0, 1, 2, 3])
        self.assertEqual(backward, [3, 2, 1, 0])
        self.assertEqual((linked.front(), linked.back()), (0, 3))
        self.assertEqual(len(linked), 4)

    def test_pushes_return_the_created_node(self):
        linked = BidirectionalChain()

        node = linked.push_back("a")

        self.assertIsInstance(node, ChainLink)
        self.assertEqual(node.value, "a")
        self.assertIs(linked.front_node(), node)
        self.assertIs(linked.back_node(), node)

    def test_pops_remove_from_each_end(self):
        linked, _ = self.build(1, 2, 3, 4)

        self.assertEqual(linked.pop_front(), 1)
        self.assertEqual(linked.pop_back(), 4)

        self.assertEqual(self.forward_and_backward(linked), ([2, 3], [3, 2]))

    def test_single_element_list_behaves_at_both_ends(self):
        linked, _ = self.build("solo")

        self.assertEqual((linked.front(), linked.back()), ("solo", "solo"))
        self.assertEqual(linked.pop_back(), "solo")
        self.assertTrue(linked.is_empty())
        linked.push_front("otra")
        self.assertEqual(linked.pop_front(), "otra")
        self.assertTrue(linked.is_empty())

    def test_remove_from_the_middle_and_the_ends(self):
        linked, (first, middle, last) = self.build("a", "b", "c")

        self.assertEqual(linked.remove(middle), "b")
        self.assertEqual(self.forward_and_backward(linked), (["a", "c"], ["c", "a"]))
        self.assertEqual(linked.remove(first), "a")
        self.assertEqual(linked.remove(last), "c")
        self.assertTrue(linked.is_empty())

    def test_removed_node_cannot_be_used_again(self):
        linked, (node,) = self.build("a")
        linked.remove(node)

        for operation in (linked.remove, linked.move_to_front, linked.move_to_back):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(ValueError):
                    operation(node)

    def test_node_from_another_list_or_a_plain_object_is_rejected(self):
        linked, _ = self.build(1)
        other, (foreign,) = self.build(9)

        with self.assertRaises(ValueError):
            linked.remove(foreign)
        with self.assertRaises(ValueError):
            linked.move_to_front("no soy un nodo")
        self.assertEqual(list(other), [9])

    def test_move_to_front_reorders_without_changing_the_size(self):
        linked, (a, b, c, d) = self.build("a", "b", "c", "d")

        linked.move_to_front(c)
        self.assertEqual(self.forward_and_backward(linked), (["c", "a", "b", "d"], ["d", "b", "a", "c"]))
        linked.move_to_front(d)
        linked.move_to_front(d)  # ya está al inicio

        self.assertEqual(list(linked), ["d", "c", "a", "b"])
        self.assertEqual(len(linked), 4)

    def test_move_to_back_reorders_without_changing_the_size(self):
        linked, (a, b, c) = self.build("a", "b", "c")

        linked.move_to_back(a)
        linked.move_to_back(a)  # ya está al final

        self.assertEqual(self.forward_and_backward(linked), (["b", "c", "a"], ["a", "c", "b"]))
        self.assertEqual(len(linked), 3)

    def test_clear_empties_and_invalidates_the_old_nodes(self):
        linked, (node, _) = self.build(1, 2)

        linked.clear()

        self.assertTrue(linked.is_empty())
        self.assertEqual(list(linked), [])
        with self.assertRaises(ValueError):
            linked.remove(node)
        linked.push_back("nuevo")
        self.assertEqual(list(linked), ["nuevo"])

    def test_matches_a_plain_list_under_random_operations(self):
        generator = random.Random(11)
        linked = BidirectionalChain()
        reference = []
        nodes = []  # nodos vivos, en el mismo orden que ``reference``
        for step in range(800):
            operation = generator.choice(
                ("front", "back", "pop_front", "pop_back", "remove", "to_front", "to_back")
            )
            if operation == "front":
                nodes.insert(0, linked.push_front(step))
                reference.insert(0, step)
            elif operation == "back":
                nodes.append(linked.push_back(step))
                reference.append(step)
            elif not reference:
                continue
            elif operation == "pop_front":
                self.assertEqual(linked.pop_front(), reference.pop(0))
                nodes.pop(0)
            elif operation == "pop_back":
                self.assertEqual(linked.pop_back(), reference.pop())
                nodes.pop()
            else:
                index = generator.randrange(len(reference))
                node = nodes[index]
                if operation == "remove":
                    self.assertEqual(linked.remove(node), reference.pop(index))
                    nodes.pop(index)
                elif operation == "to_front":
                    linked.move_to_front(node)
                    nodes.insert(0, nodes.pop(index))
                    reference.insert(0, reference.pop(index))
                else:
                    linked.move_to_back(node)
                    nodes.append(nodes.pop(index))
                    reference.append(reference.pop(index))

            self.assertEqual(list(linked), reference)
            self.assertEqual(list(linked.reversed()), reference[::-1])
            self.assertEqual(len(linked), len(reference))


class LeastRecentlyUsedCacheTests(SimpleTestCase):
    def test_capacity_must_be_a_positive_integer(self):
        for capacity in (0, -1, 2.5, "3", None, True):
            with self.subTest(capacity=capacity):
                with self.assertRaises(ValueError):
                    LeastRecentlyUsedCache(capacity)

    def test_new_cache_is_empty(self):
        cache = LeastRecentlyUsedCache(2)

        self.assertEqual(len(cache), 0)
        self.assertEqual(cache.keys(), [])
        self.assertEqual(cache.capacity, 2)
        self.assertIsNone(cache.get("x"))
        self.assertEqual(cache.get("x", "por defecto"), "por defecto")

    def test_put_then_get_returns_the_value(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)

        self.assertEqual(cache.get("a"), 1)
        self.assertIn("a", cache)
        self.assertEqual(len(cache), 1)

    def test_full_cache_evicts_the_least_recently_used(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)
        cache.put("b", 2)

        evicted = cache.put("c", 3)

        self.assertEqual(evicted, ("a", 1))
        self.assertNotIn("a", cache)
        self.assertEqual(cache.keys(), ["c", "b"])

    def test_get_makes_an_entry_recent_so_another_is_evicted(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")

        evicted = cache.put("c", 3)

        self.assertEqual(evicted, ("b", 2))
        self.assertEqual(cache.keys(), ["c", "a"])

    def test_updating_an_existing_key_does_not_evict_and_makes_it_recent(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)
        cache.put("b", 2)

        self.assertIsNone(cache.put("a", 10))

        self.assertEqual(cache.items(), [("a", 10), ("b", 2)])
        self.assertEqual(len(cache), 2)

    def test_capacity_one_keeps_only_the_last_entry(self):
        cache = LeastRecentlyUsedCache(1)

        self.assertIsNone(cache.put("a", 1))
        self.assertEqual(cache.put("b", 2), ("a", 1))
        self.assertEqual(cache.put("c", 3), ("b", 2))

        self.assertEqual(cache.items(), [("c", 3)])
        self.assertIsNone(cache.get("a"))

    def test_peek_and_contains_do_not_change_the_order(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)
        cache.put("b", 2)

        self.assertEqual(cache.peek("a"), 1)
        self.assertIn("a", cache)
        self.assertEqual(cache.peek("zzz", "no"), "no")
        evicted = cache.put("c", 3)

        self.assertEqual(evicted, ("a", 1))

    def test_discard_removes_an_entry_and_frees_a_slot(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)
        cache.put("b", 2)

        self.assertTrue(cache.discard("a"))
        self.assertFalse(cache.discard("a"))
        self.assertIsNone(cache.put("c", 3))

        self.assertEqual(cache.keys(), ["c", "b"])

    def test_none_and_falsy_values_are_stored(self):
        cache = LeastRecentlyUsedCache(3)
        cache.put("none", None)
        cache.put("zero", 0)
        cache.put("vacio", "")

        self.assertIn("none", cache)
        self.assertEqual(cache.get("zero", "otro"), 0)
        self.assertEqual(cache.get("vacio", "otro"), "")

    def test_keys_can_be_any_hashable(self):
        cache = LeastRecentlyUsedCache(3)
        cache.put(("nodo", 1), "a")
        cache.put(42, "b")
        cache.put(None, "c")

        self.assertEqual(cache.get(("nodo", 1)), "a")
        self.assertEqual(cache.get(None), "c")
        with self.assertRaises(TypeError):
            cache.put([1, 2], "no hashable")

    def test_hits_and_misses_are_counted_only_by_get(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)

        cache.get("a")
        cache.get("a")
        cache.get("zzz")
        cache.peek("a")
        "a" in cache

        self.assertEqual((cache.hits, cache.misses), (2, 1))
        cache.reset_stats()
        self.assertEqual((cache.hits, cache.misses), (0, 0))

    def test_clear_empties_the_cache_and_it_can_be_reused(self):
        cache = LeastRecentlyUsedCache(2)
        cache.put("a", 1)
        cache.put("b", 2)

        cache.clear()

        self.assertEqual(len(cache), 0)
        self.assertEqual(cache.keys(), [])
        cache.put("z", 26)
        self.assertEqual(cache.items(), [("z", 26)])

    def test_matches_a_reference_model_under_random_operations(self):
        generator = random.Random(2027)
        capacity = 6
        cache = LeastRecentlyUsedCache(capacity)
        model = OrderedDict()  # el último es el más reciente
        for step in range(3000):
            key = generator.randrange(15)
            operation = generator.choice(("get", "get", "put", "put", "peek", "discard"))
            if operation == "get":
                expected = model.get(key)
                if key in model:
                    model.move_to_end(key)
                self.assertEqual(cache.get(key), expected)
            elif operation == "put":
                evicted = None
                if key in model:
                    model.move_to_end(key)
                elif len(model) == capacity:
                    evicted = model.popitem(last=False)
                model[key] = step
                self.assertEqual(cache.put(key, step), evicted)
            elif operation == "peek":
                self.assertEqual(cache.peek(key), model.get(key))
            else:
                self.assertEqual(cache.discard(key), model.pop(key, None) is not None)

            self.assertEqual(cache.keys(), list(reversed(model)))
            self.assertEqual(len(cache), len(model))


class FirstInFirstOutQueueTests(SimpleTestCase):
    def test_new_queue_is_empty(self):
        queue = FirstInFirstOutQueue()

        self.assertEqual(len(queue), 0)
        self.assertTrue(queue.is_empty())
        self.assertEqual(list(queue), [])

    def test_empty_queue_rejects_dequeue_and_peek(self):
        queue = FirstInFirstOutQueue()

        with self.assertRaises(IndexError):
            queue.dequeue()
        with self.assertRaises(IndexError):
            queue.peek()

    def test_first_in_first_out_order(self):
        queue = FirstInFirstOutQueue()
        for value in ("a", "b", "c"):
            queue.enqueue(value)

        self.assertEqual([queue.dequeue() for _ in range(3)], ["a", "b", "c"])
        self.assertTrue(queue.is_empty())

    def test_peek_does_not_remove(self):
        queue = FirstInFirstOutQueue([1, 2])

        self.assertEqual(queue.peek(), 1)
        self.assertEqual(queue.peek(), 1)
        self.assertEqual(len(queue), 2)

    def test_constructor_accepts_an_iterable_in_order(self):
        queue = FirstInFirstOutQueue(range(4))

        self.assertEqual(list(queue), [0, 1, 2, 3])
        self.assertEqual(len(queue), 4)

    def test_iteration_does_not_consume_the_queue(self):
        queue = FirstInFirstOutQueue("xyz")

        self.assertEqual(list(queue), list(queue))
        self.assertEqual(len(queue), 3)

    def test_emptying_and_refilling_keeps_the_links_consistent(self):
        queue = FirstInFirstOutQueue()
        queue.enqueue(1)
        self.assertEqual(queue.dequeue(), 1)
        self.assertTrue(queue.is_empty())

        queue.enqueue(2)
        queue.enqueue(3)

        self.assertEqual(list(queue), [2, 3])
        self.assertEqual(queue.dequeue(), 2)
        self.assertEqual(queue.dequeue(), 3)
        with self.assertRaises(IndexError):
            queue.dequeue()

    def test_none_and_falsy_items_are_valid(self):
        queue = FirstInFirstOutQueue([None, 0, ""])

        self.assertEqual(len(queue), 3)
        self.assertEqual([queue.dequeue() for _ in range(3)], [None, 0, ""])

    def test_clear_empties_the_queue_and_it_can_be_reused(self):
        queue = FirstInFirstOutQueue(range(5))

        queue.clear()

        self.assertTrue(queue.is_empty())
        with self.assertRaises(IndexError):
            queue.peek()
        queue.enqueue("nuevo")
        self.assertEqual(list(queue), ["nuevo"])

    def test_matches_a_plain_list_under_random_operations(self):
        generator = random.Random(5)
        queue = FirstInFirstOutQueue()
        reference = []
        for step in range(2000):
            if reference and generator.random() < 0.45:
                self.assertEqual(queue.dequeue(), reference.pop(0))
            else:
                queue.enqueue(step)
                reference.append(step)

            self.assertEqual(len(queue), len(reference))
            if reference:
                self.assertEqual(queue.peek(), reference[0])
        self.assertEqual(list(queue), reference)

    def test_large_queue_dequeues_everything_in_order(self):
        queue = FirstInFirstOutQueue(range(10000))

        self.assertEqual([queue.dequeue() for _ in range(10000)], list(range(10000)))
        self.assertTrue(queue.is_empty())


class PriorityMinHeapTests(SimpleTestCase):
    def test_new_heap_is_empty(self):
        heap = PriorityMinHeap()

        self.assertEqual(len(heap), 0)
        self.assertTrue(heap.is_empty())

    def test_empty_heap_has_no_top(self):
        heap = PriorityMinHeap()

        with self.assertRaises(IndexError):
            heap.peek()
        with self.assertRaises(IndexError):
            heap.pop()

    def test_priority_must_be_callable(self):
        with self.assertRaises(TypeError):
            PriorityMinHeap(priority=3)

    def test_items_come_out_from_smallest_to_largest(self):
        heap = PriorityMinHeap()
        for value in (5, 1, 4, 2, 3):
            heap.push(value)

        self.assertEqual(heap.peek(), 1)
        self.assertEqual([heap.pop() for _ in range(5)], [1, 2, 3, 4, 5])
        self.assertTrue(heap.is_empty())

    def test_peek_does_not_remove(self):
        heap = PriorityMinHeap()
        heap.push(2)
        heap.push(1)

        self.assertEqual(heap.peek(), 1)
        self.assertEqual(len(heap), 2)

    def test_custom_priority_function(self):
        heap = PriorityMinHeap(priority=lambda word: len(word))
        for word in ("pino", "a", "bosque", "fuego"):
            heap.push(word)

        self.assertEqual([heap.pop() for _ in range(4)], ["a", "pino", "fuego", "bosque"])

    def test_negated_priority_gives_the_largest_first(self):
        heap = PriorityMinHeap(priority=lambda value: -value)
        for value in (3, 9, 1, 7):
            heap.push(value)

        self.assertEqual([heap.pop() for _ in range(4)], [9, 7, 3, 1])

    def test_ties_come_out_in_insertion_order(self):
        heap = PriorityMinHeap(priority=lambda pair: pair[0])
        for pair in ((1, "a"), (0, "x"), (1, "b"), (1, "c"), (0, "y")):
            heap.push(pair)

        self.assertEqual(
            [heap.pop() for _ in range(5)],
            [(0, "x"), (0, "y"), (1, "a"), (1, "b"), (1, "c")],
        )

    def test_items_that_cannot_be_compared_work_with_a_priority(self):
        heap = PriorityMinHeap(priority=lambda item: item["score"])
        heap.push({"score": 2})
        heap.push({"score": 2})
        heap.push({"score": 1})

        self.assertEqual(heap.pop(), {"score": 1})
        self.assertEqual(len(heap), 2)

    def test_pushing_after_popping_keeps_the_order(self):
        heap = PriorityMinHeap()
        for value in (4, 2, 6):
            heap.push(value)
        self.assertEqual(heap.pop(), 2)
        heap.push(1)
        heap.push(5)

        self.assertEqual([heap.pop() for _ in range(4)], [1, 4, 5, 6])

    def test_single_item(self):
        heap = PriorityMinHeap()
        heap.push("solo")

        self.assertEqual(heap.pop(), "solo")
        self.assertTrue(heap.is_empty())

    def test_from_items_matches_sorting(self):
        rng = random.Random(7)
        values = [rng.randint(-50, 50) for _ in range(200)]

        heap = PriorityMinHeap.from_items(values)

        self.assertEqual(len(heap), 200)
        self.assertEqual([heap.pop() for _ in range(200)], sorted(values))

    def test_from_items_keeps_ties_in_input_order(self):
        items = [(1, "a"), (0, "b"), (1, "c"), (0, "d")]

        heap = PriorityMinHeap.from_items(items, priority=lambda pair: pair[0])

        self.assertEqual([heap.pop() for _ in range(4)], [(0, "b"), (0, "d"), (1, "a"), (1, "c")])

    def test_random_operations_match_a_sorted_list(self):
        rng = random.Random(11)
        heap = PriorityMinHeap()
        reference = []
        for _ in range(500):
            if reference and rng.random() < 0.4:
                reference.sort()
                self.assertEqual(heap.pop(), reference.pop(0))
            else:
                value = rng.randint(0, 30)
                heap.push(value)
                reference.append(value)
            self.assertEqual(len(heap), len(reference))

    def test_smallest_returns_the_top_k_in_order(self):
        values = [9, 3, 7, 1, 8, 2]

        self.assertEqual(PriorityMinHeap.smallest(values, 3), [1, 2, 3])
        self.assertEqual(PriorityMinHeap.smallest(values, 0), [])
        self.assertEqual(PriorityMinHeap.smallest(values, 99), sorted(values))
        self.assertEqual(PriorityMinHeap.smallest([], 2), [])

    def test_smallest_with_priority_gives_the_riskiest_nodes(self):
        nodes = [("a", 0.2), ("b", 0.9), ("c", 0.5), ("d", 0.9)]

        top = PriorityMinHeap.smallest(nodes, 2, priority=lambda node: -node[1])

        self.assertEqual(top, [("b", 0.9), ("d", 0.9)])

    def test_smallest_rejects_an_invalid_k(self):
        for k in (-1, 1.5, "2", None, True):
            with self.subTest(k=k):
                with self.assertRaises(ValueError):
                    PriorityMinHeap.smallest([1, 2], k)


class PrefixTrieTests(SimpleTestCase):
    def setUp(self):
        self.trie = PrefixTrie()
        for word in ("nodo-1", "nodo-12", "nodo-2", "sensor-a", "Nodo-3"):
            self.trie.insert(word)

    def test_new_trie_is_empty(self):
        trie = PrefixTrie()

        self.assertEqual(len(trie), 0)
        self.assertEqual(trie.with_prefix(""), [])
        self.assertFalse(trie.contains("nodo"))

    def test_insert_counts_only_new_words(self):
        trie = PrefixTrie()

        self.assertTrue(trie.insert("pino"))
        self.assertFalse(trie.insert("pino"))
        self.assertFalse(trie.insert("PINO"))
        self.assertEqual(len(trie), 1)

    def test_empty_or_non_text_words_are_rejected(self):
        with self.assertRaises(ValueError):
            self.trie.insert("")
        for value in (None, 5, b"nodo"):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    self.trie.insert(value)
                with self.assertRaises(TypeError):
                    self.trie.contains(value)
                with self.assertRaises(TypeError):
                    self.trie.with_prefix(value)

    def test_contains_needs_the_whole_word(self):
        self.assertTrue(self.trie.contains("nodo-1"))
        self.assertTrue("nodo-12" in self.trie)
        self.assertFalse(self.trie.contains("nodo"))
        self.assertFalse(self.trie.contains("nodo-123"))

    def test_prefix_returns_every_word_in_alphabetical_order(self):
        self.assertEqual(
            self.trie.with_prefix("nodo-1"),
            ["nodo-1", "nodo-12"],
        )
        self.assertEqual(
            self.trie.with_prefix("nodo"),
            ["nodo-1", "nodo-12", "nodo-2", "Nodo-3"],
        )

    def test_empty_prefix_returns_everything(self):
        self.assertEqual(len(self.trie.with_prefix("")), 5)
        self.assertEqual(self.trie.with_prefix("")[0], "nodo-1")

    def test_unknown_prefix_returns_nothing(self):
        self.assertEqual(self.trie.with_prefix("zzz"), [])
        self.assertEqual(self.trie.with_prefix("nodo-9"), [])

    def test_search_ignores_case_but_keeps_the_original_spelling(self):
        self.assertTrue(self.trie.contains("NODO-3"))
        self.assertEqual(self.trie.with_prefix("NODO-3"), ["Nodo-3"])
        self.assertEqual(self.trie.with_prefix("Sen"), ["sensor-a"])

    def test_limit_cuts_the_results(self):
        self.assertEqual(self.trie.with_prefix("nodo", limit=2), ["nodo-1", "nodo-12"])
        self.assertEqual(self.trie.with_prefix("nodo", limit=0), [])
        self.assertEqual(len(self.trie.with_prefix("nodo", limit=99)), 4)

    def test_invalid_limit_is_rejected(self):
        for limit in (-1, 1.5, "2", True):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.trie.with_prefix("nodo", limit=limit)

    def test_delete_removes_only_that_word(self):
        self.assertTrue(self.trie.delete("nodo-1"))

        self.assertFalse(self.trie.contains("nodo-1"))
        self.assertTrue(self.trie.contains("nodo-12"))
        self.assertEqual(self.trie.with_prefix("nodo-1"), ["nodo-12"])
        self.assertEqual(len(self.trie), 4)

    def test_delete_of_a_missing_word_or_a_bare_prefix_does_nothing(self):
        self.assertFalse(self.trie.delete("nodo"))
        self.assertFalse(self.trie.delete("nada"))
        self.assertFalse(self.trie.delete("nodo-123"))
        self.assertEqual(len(self.trie), 5)

    def test_delete_prunes_empty_branches(self):
        trie = PrefixTrie()
        trie.insert("abc")
        trie.delete("abc")

        self.assertEqual(len(trie), 0)
        self.assertEqual(trie._root.children, {})

    def test_delete_keeps_branches_shared_with_other_words(self):
        trie = PrefixTrie()
        trie.insert("ab")
        trie.insert("abc")
        trie.delete("abc")

        self.assertTrue(trie.contains("ab"))
        self.assertEqual(trie.with_prefix("a"), ["ab"])

    def test_a_deleted_word_can_be_inserted_again(self):
        self.trie.delete("sensor-a")

        self.assertTrue(self.trie.insert("Sensor-A"))
        self.assertEqual(self.trie.with_prefix("sensor"), ["Sensor-A"])

    def test_matches_a_brute_force_search(self):
        rng = random.Random(3)
        words = {"".join(rng.choice("abc") for _ in range(rng.randint(1, 5))) for _ in range(60)}
        trie = PrefixTrie()
        for word in words:
            trie.insert(word)

        for prefix in ("", "a", "ab", "abc", "ca", "cc", "bbb"):
            expected = sorted(word for word in words if word.startswith(prefix))
            self.assertEqual(trie.with_prefix(prefix), expected)
