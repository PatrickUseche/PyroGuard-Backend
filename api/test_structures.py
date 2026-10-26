import random

from django.test import SimpleTestCase

from .structures.ring_buffer import RingBuffer
from .structures.sliding_window import SlidingWindow


class RingBufferTests(SimpleTestCase):
    def test_capacity_must_be_a_positive_integer(self):
        for capacity in (0, -1, 1.5, "3", None, True):
            with self.subTest(capacity=capacity):
                with self.assertRaises(ValueError):
                    RingBuffer(capacity)

    def test_new_buffer_is_empty(self):
        buffer = RingBuffer(3)

        self.assertEqual(len(buffer), 0)
        self.assertTrue(buffer.is_empty())
        self.assertFalse(buffer.is_full())
        self.assertEqual(list(buffer), [])
        self.assertEqual(buffer.capacity, 3)

    def test_empty_buffer_has_no_oldest_or_newest(self):
        buffer = RingBuffer(2)

        with self.assertRaises(IndexError):
            buffer.oldest()
        with self.assertRaises(IndexError):
            buffer.newest()
        with self.assertRaises(IndexError):
            buffer[0]

    def test_items_are_kept_in_insertion_order_until_full(self):
        buffer = RingBuffer(3)
        for value in (1, 2):
            self.assertIsNone(buffer.append(value))

        self.assertEqual(list(buffer), [1, 2])
        self.assertEqual(len(buffer), 2)
        self.assertFalse(buffer.is_full())

        buffer.append(3)
        self.assertTrue(buffer.is_full())
        self.assertEqual(list(buffer), [1, 2, 3])

    def test_full_buffer_overwrites_the_oldest_and_returns_it(self):
        buffer = RingBuffer(3)
        for value in (1, 2, 3):
            buffer.append(value)

        self.assertEqual(buffer.append(4), 1)
        self.assertEqual(buffer.append(5), 2)

        self.assertEqual(list(buffer), [3, 4, 5])
        self.assertEqual(len(buffer), 3)

    def test_oldest_and_newest_follow_the_overwrites(self):
        buffer = RingBuffer(3)
        for value in range(1, 8):
            buffer.append(value)

        self.assertEqual(buffer.oldest(), 5)
        self.assertEqual(buffer.newest(), 7)

    def test_indexing_counts_from_the_oldest_and_supports_negatives(self):
        buffer = RingBuffer(3)
        for value in range(10, 15):
            buffer.append(value)

        self.assertEqual([buffer[0], buffer[1], buffer[2]], [12, 13, 14])
        self.assertEqual(buffer[-1], 14)
        self.assertEqual(buffer[-3], 12)

    def test_index_out_of_range_or_wrong_type_is_rejected(self):
        buffer = RingBuffer(3)
        buffer.append("a")

        for index in (1, 3, -2, 99):
            with self.subTest(index=index):
                with self.assertRaises(IndexError):
                    buffer[index]
        with self.assertRaises(TypeError):
            buffer["0"]

    def test_capacity_one_always_keeps_the_last_item(self):
        buffer = RingBuffer(1)

        self.assertIsNone(buffer.append("a"))
        self.assertEqual(buffer.append("b"), "a")
        self.assertEqual(buffer.append("c"), "b")

        self.assertEqual(list(buffer), ["c"])
        self.assertEqual(buffer.oldest(), buffer.newest())

    def test_wraps_around_many_times_keeping_the_last_k_items(self):
        buffer = RingBuffer(4)
        for value in range(1000):
            buffer.append(value)

        self.assertEqual(list(buffer), [996, 997, 998, 999])

    def test_none_is_a_valid_item(self):
        buffer = RingBuffer(2)
        buffer.append(None)
        buffer.append(None)

        self.assertEqual(len(buffer), 2)
        self.assertEqual(list(buffer), [None, None])

    def test_clear_empties_the_buffer_and_it_can_be_reused(self):
        buffer = RingBuffer(3)
        for value in range(5):
            buffer.append(value)

        buffer.clear()

        self.assertTrue(buffer.is_empty())
        self.assertEqual(list(buffer), [])
        buffer.append("x")
        self.assertEqual(list(buffer), ["x"])
        self.assertEqual(buffer.oldest(), "x")

    def test_iteration_does_not_consume_the_buffer(self):
        buffer = RingBuffer(3)
        for value in (1, 2, 3):
            buffer.append(value)

        self.assertEqual(list(buffer), list(buffer))
        self.assertEqual(len(buffer), 3)

    def test_matches_a_plain_list_of_the_last_k_items(self):
        capacity = 5
        buffer = RingBuffer(capacity)
        reference = []
        for value in range(37):
            buffer.append(value)
            reference.append(value)
            reference = reference[-capacity:]

            self.assertEqual(list(buffer), reference)


def brute_force_extremes(values, size):
    window = values[-size:]
    return max(window), min(window)


class SlidingWindowTests(SimpleTestCase):
    def test_size_must_be_a_positive_integer(self):
        for size in (0, -3, 2.5, "4", None, True):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    SlidingWindow(size)

    def test_empty_window_has_no_extremes(self):
        window = SlidingWindow(3)

        self.assertTrue(window.is_empty())
        self.assertEqual(len(window), 0)
        with self.assertRaises(ValueError):
            window.maximum
        with self.assertRaises(ValueError):
            window.minimum

    def test_only_numbers_are_accepted(self):
        window = SlidingWindow(3)

        for value in ("5", None, True, [1], (2,)):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    window.push(value)
        with self.assertRaises(ValueError):
            window.push(float("nan"))
        self.assertTrue(window.is_empty())

    def test_single_value_is_both_extremes(self):
        window = SlidingWindow(3)
        window.push(7)

        self.assertEqual((window.maximum, window.minimum), (7, 7))
        self.assertEqual(len(window), 1)
        self.assertFalse(window.is_full())

    def test_old_extreme_leaves_when_it_slides_out(self):
        window = SlidingWindow(3)
        for value in (10, 1, 2):
            window.push(value)
        self.assertEqual((window.maximum, window.minimum), (10, 1))

        window.push(3)  # sale el 10
        self.assertEqual((window.maximum, window.minimum), (3, 1))

        window.push(4)  # sale el 1
        self.assertEqual((window.maximum, window.minimum), (4, 2))

    def test_window_of_one_tracks_the_last_value(self):
        window = SlidingWindow(1)
        for value in (5, 3, 9, -2):
            window.push(value)

            self.assertEqual((window.maximum, window.minimum), (value, value))

    def test_repeated_values_do_not_expire_early(self):
        window = SlidingWindow(3)
        for value in (5, 5, 5):
            window.push(value)
        window.push(1)  # sale un 5, quedan dos
        self.assertEqual(window.maximum, 5)

        window.push(1)  # queda un 5
        self.assertEqual(window.maximum, 5)

        window.push(1)  # ya no queda ningún 5
        self.assertEqual((window.maximum, window.minimum), (1, 1))

    def test_monotonic_sequences(self):
        increasing = SlidingWindow(4)
        decreasing = SlidingWindow(4)
        for value in range(20):
            increasing.push(value)
            decreasing.push(-value)

        self.assertEqual((increasing.maximum, increasing.minimum), (19, 16))
        self.assertEqual((decreasing.maximum, decreasing.minimum), (-16, -19))

    def test_floats_and_negatives(self):
        window = SlidingWindow(2)
        for value in (-1.5, 2.25, -3.0):
            window.push(value)

        self.assertEqual((window.maximum, window.minimum), (2.25, -3.0))

    def test_len_and_is_full_follow_the_window(self):
        window = SlidingWindow(3)
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
                window = SlidingWindow(size)
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
        window = SlidingWindow(8)
        values = []
        for _ in range(300):
            value = round(generator.uniform(-40, 120), 2)
            values.append(value)
            window.push(value)

            self.assertEqual(
                (window.maximum, window.minimum), brute_force_extremes(values, 8)
            )

    def test_long_runs_keep_working_after_the_internal_compaction(self):
        window = SlidingWindow(200)
        values = []
        for index in range(5000):
            value = (index * 37) % 101
            values.append(value)
            window.push(value)

        self.assertEqual(
            (window.maximum, window.minimum), brute_force_extremes(values, 200)
        )
