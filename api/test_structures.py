from django.test import SimpleTestCase

from .structures.ring_buffer import RingBuffer


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
