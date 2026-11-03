"""Pruebas de la serie de lecturas: búsqueda binaria, promedios, mezcla y endpoint."""
import random
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from .models import Node, SensorReading
from .services import series_queries
from .services.series import (
    MAX_BUCKETS,
    TimeSeries,
    lower_bound,
    merge_sorted,
    upper_bound,
)

_unlimited_rates = patch.object(
    SimpleRateThrottle,
    "THROTTLE_RATES",
    {"read": None, "ingest": None, "login": None},
)


def setUpModule():
    _unlimited_rates.start()


def tearDownModule():
    _unlimited_rates.stop()


BASE = datetime(2026, 10, 30, 12, 0, tzinfo=dt_timezone.utc)


def at(minutes):
    return BASE + timedelta(minutes=minutes)


class BinarySearchTests(SimpleTestCase):
    def test_bounds_on_a_list_with_repeats(self):
        values = [1, 2, 2, 2, 5, 8]

        self.assertEqual(lower_bound(values, 2), 1)
        self.assertEqual(upper_bound(values, 2), 4)
        self.assertEqual(lower_bound(values, 3), 4)
        self.assertEqual(upper_bound(values, 3), 4)

    def test_bounds_outside_the_list(self):
        values = [10, 20, 30]

        self.assertEqual(lower_bound(values, 0), 0)
        self.assertEqual(upper_bound(values, 0), 0)
        self.assertEqual(lower_bound(values, 99), 3)
        self.assertEqual(upper_bound(values, 99), 3)

    def test_empty_list(self):
        self.assertEqual(lower_bound([], 5), 0)
        self.assertEqual(upper_bound([], 5), 0)

    def test_it_matches_a_linear_scan(self):
        rng = random.Random(4)
        values = sorted(rng.randint(0, 30) for _ in range(80))
        for target in range(-2, 34):
            self.assertEqual(lower_bound(values, target), sum(1 for v in values if v < target))
            self.assertEqual(upper_bound(values, target), sum(1 for v in values if v <= target))


class TimeSeriesTests(SimpleTestCase):
    def setUp(self):
        # un punto por minuto, valores 0, 10, 20, ... 90
        self.series = TimeSeries([(at(minute), minute * 10) for minute in range(10)])

    def test_points_must_be_sorted(self):
        with self.assertRaises(ValueError):
            TimeSeries([(at(5), 1), (at(1), 2)])

    def test_empty_series(self):
        empty = TimeSeries([])

        self.assertEqual(len(empty), 0)
        self.assertIsNone(empty.mean_between())
        self.assertEqual(empty.points_between(), [])
        self.assertEqual(empty.buckets(at(0), at(10), 60), [])

    def test_range_includes_both_ends(self):
        self.assertEqual(self.series.index_range(at(2), at(4)), (2, 5))
        self.assertEqual(
            [value for _, value in self.series.points_between(at(2), at(4))], [20, 30, 40]
        )

    def test_open_ended_ranges(self):
        self.assertEqual(self.series.index_range(None, None), (0, 10))
        self.assertEqual(self.series.index_range(at(8), None), (8, 10))
        self.assertEqual(self.series.index_range(None, at(1)), (0, 2))

    def test_a_range_without_points(self):
        self.assertEqual(self.series.index_range(at(20), at(30)), (10, 10))
        self.assertEqual(self.series.index_range(at(5) + timedelta(seconds=10), at(5) + timedelta(seconds=20)), (6, 6))
        self.assertEqual(self.series.index_range(at(5), at(3)), (5, 5))
        self.assertIsNone(self.series.mean_between(at(20), at(30)))

    def test_mean_between(self):
        self.assertEqual(self.series.mean_between(at(0), at(9)), 45)
        self.assertEqual(self.series.mean_between(at(2), at(4)), 30)
        self.assertEqual(self.series.mean_between(at(7), at(7)), 70)

    def test_mean_matches_a_direct_average_on_random_ranges(self):
        rng = random.Random(8)
        points = [(at(minute), rng.uniform(0, 100)) for minute in range(200)]
        series = TimeSeries(points)
        for _ in range(100):
            first, last = sorted(rng.randrange(200) for _ in range(2))
            expected = [value for when, value in points if at(first) <= when <= at(last)]
            self.assertAlmostEqual(series.mean_between(at(first), at(last)), sum(expected) / len(expected))

    def test_buckets_are_aligned_to_the_clock_and_skip_empty_ones(self):
        series = TimeSeries([(at(1), 10), (at(2), 20), (at(12), 100)])

        buckets = series.buckets(at(0), at(14), 300)  # tramos de 5 minutos

        self.assertEqual(
            buckets,
            [
                {"start": at(0), "count": 2, "average": 15},
                {"start": at(10), "count": 1, "average": 100},
            ],
        )

    def test_a_bucket_starts_at_a_multiple_of_the_step(self):
        series = TimeSeries([(at(7), 5)])

        (bucket,) = series.buckets(at(7), at(9), 300)

        self.assertEqual(bucket["start"], at(5))

    def test_buckets_respect_the_requested_range(self):
        series = TimeSeries([(at(minute), minute) for minute in range(10)])

        buckets = series.buckets(at(3), at(6), 3600)

        self.assertEqual(buckets, [{"start": at(0), "count": 4, "average": 4.5}])

    def test_the_end_of_the_range_is_included(self):
        series = TimeSeries([(at(5), 1), (at(10), 3)])

        (bucket,) = series.buckets(at(5), at(10), 3600)

        self.assertEqual(bucket["count"], 2)

    def test_buckets_cover_every_point_exactly_once(self):
        rng = random.Random(2)
        points = [(at(minute * 3), rng.uniform(0, 50)) for minute in range(100)]
        series = TimeSeries(points)

        buckets = series.buckets(at(0), at(300), 600)

        self.assertEqual(sum(bucket["count"] for bucket in buckets), len(points))
        total = sum(bucket["count"] * bucket["average"] for bucket in buckets)
        self.assertAlmostEqual(total, sum(value for _, value in points))

    def test_too_many_buckets_are_refused(self):
        with self.assertRaises(ValueError):
            self.series.buckets(at(0), at(0) + timedelta(seconds=MAX_BUCKETS + 5), 1)
        with self.assertRaises(ValueError):
            self.series.buckets(at(0), at(10), 0)


class MergeSortedTests(SimpleTestCase):
    def test_merges_sorted_lists(self):
        merged = merge_sorted([[1, 4, 7], [2, 5, 8], [3, 6, 9]], key=lambda value: value)

        self.assertEqual(merged, [1, 2, 3, 4, 5, 6, 7, 8, 9])

    def test_empty_inputs(self):
        self.assertEqual(merge_sorted([], key=lambda value: value), [])
        self.assertEqual(merge_sorted([[], []], key=lambda value: value), [])
        self.assertEqual(merge_sorted([[], [1, 2], []], key=lambda value: value), [1, 2])

    def test_a_single_list_is_returned_as_is(self):
        self.assertEqual(merge_sorted([[1, 2, 3]], key=lambda value: value), [1, 2, 3])

    def test_lists_of_different_lengths(self):
        merged = merge_sorted([[1], [2, 3, 4, 5], [0, 6]], key=lambda value: value)

        self.assertEqual(merged, [0, 1, 2, 3, 4, 5, 6])

    def test_ties_keep_the_order_of_the_lists(self):
        merged = merge_sorted(
            [[("a", 1), ("a", 2)], [("b", 1), ("b", 2)]], key=lambda item: item[1]
        )

        self.assertEqual(merged, [("a", 1), ("b", 1), ("a", 2), ("b", 2)])

    def test_it_does_not_modify_the_inputs(self):
        lists = [[1, 3], [2, 4]]

        merge_sorted(lists, key=lambda value: value)

        self.assertEqual(lists, [[1, 3], [2, 4]])

    def test_it_matches_sorting_everything(self):
        rng = random.Random(6)
        lists = [sorted(rng.randint(0, 50) for _ in range(rng.randint(0, 30))) for _ in range(9)]

        merged = merge_sorted(lists, key=lambda value: value)

        self.assertEqual(merged, sorted(value for items in lists for value in items))


class SeriesEndpointTests(APITestCase):
    def setUp(self):
        self.node_a = Node.objects.create(node_id="A")
        self.node_b = Node.objects.create(node_id="B")

    def reading(self, node, minutes, temperature=20.0, humidity=40.0, gas=None):
        return SensorReading.objects.create(
            node=node, temperature=temperature, humidity=humidity, smoke=1, gas=gas,
            flame=False, timestamp=at(minutes),
        )

    def series(self, **params):
        params.setdefault("from", at(-5).isoformat())
        params.setdefault("to", at(60).isoformat())
        return self.client.get(reverse("reading_series"), params)

    def test_returns_the_points_of_a_node_in_order(self):
        for minute, temperature in ((3, 30), (1, 10), (2, 20)):
            self.reading(self.node_a, minute, temperature=temperature)

        response = self.series(node_id="A")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["field"], "temperature")
        (entry,) = response.data["series"]
        self.assertEqual(entry["node_id"], "A")
        self.assertEqual(entry["count"], 3)
        self.assertEqual(entry["average"], 20)
        self.assertEqual([p["value"] for p in entry["points"]], [10, 20, 30])
        self.assertNotIn("buckets", entry)

    def test_only_the_requested_range_is_returned(self):
        for minute in range(10):
            self.reading(self.node_a, minute, temperature=minute)

        response = self.series(node_id="A", **{"from": at(3).isoformat(), "to": at(5).isoformat()})

        (entry,) = response.data["series"]
        self.assertEqual([p["value"] for p in entry["points"]], [3, 4, 5])
        self.assertEqual(entry["average"], 4)

    def test_another_field(self):
        self.reading(self.node_a, 1, humidity=55)

        response = self.series(node_id="A", field="humidity")

        self.assertEqual(response.data["series"][0]["points"][0]["value"], 55)

    def test_readings_without_the_field_are_skipped(self):
        self.reading(self.node_a, 1, gas=None)
        self.reading(self.node_a, 2, gas=7)

        response = self.series(node_id="A", field="gas")

        self.assertEqual([p["value"] for p in response.data["series"][0]["points"]], [7])

    def test_step_returns_averaged_buckets(self):
        for minute in (1, 2, 3, 11):
            self.reading(self.node_a, minute, temperature=minute * 10)

        response = self.series(node_id="A", step=300)

        (entry,) = response.data["series"]
        self.assertNotIn("points", entry)
        self.assertEqual([(b["count"], b["average"]) for b in entry["buckets"]], [(3, 20), (1, 110)])
        self.assertEqual(response.data["step"], 300)

    def test_a_node_without_readings_returns_empty_data(self):
        response = self.series(node_id="A")

        (entry,) = response.data["series"]
        self.assertEqual(entry["count"], 0)
        self.assertIsNone(entry["average"])
        self.assertEqual(entry["points"], [])

    def test_several_nodes_in_one_request(self):
        self.reading(self.node_a, 1, temperature=10)
        self.reading(self.node_b, 2, temperature=50)

        response = self.series(node_id=["A", "B"])

        self.assertEqual([e["node_id"] for e in response.data["series"]], ["A", "B"])
        self.assertNotIn("merged", response.data)

    def test_node_ids_can_be_comma_separated_and_repeated_ones_are_ignored(self):
        response = self.series(node_id=["A,B", "A"])

        self.assertEqual([e["node_id"] for e in response.data["series"]], ["A", "B"])

    def test_merge_puts_every_node_on_a_single_timeline(self):
        self.reading(self.node_a, 1, temperature=10)
        self.reading(self.node_a, 4, temperature=40)
        self.reading(self.node_b, 2, temperature=20)
        self.reading(self.node_b, 3, temperature=30)

        response = self.series(node_id="A,B", merge="true")

        merged = response.data["merged"]
        self.assertEqual([(m["node_id"], m["value"]) for m in merged],
                         [("A", 10), ("B", 20), ("B", 30), ("A", 40)])
        timestamps = [m["timestamp"] for m in merged]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_merge_with_buckets(self):
        self.reading(self.node_a, 1, temperature=10)
        self.reading(self.node_b, 6, temperature=60)
        self.reading(self.node_a, 7, temperature=70)

        response = self.series(node_id="A,B", merge="1", step=300)

        merged = response.data["merged"]
        self.assertEqual(
            [(m["node_id"], m["average"]) for m in merged],
            [("A", 10), ("A", 70), ("B", 60)],
        )
        starts = [m["start"] for m in merged]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual({m["node_id"] for m in merged}, {"A", "B"})

    def test_merge_off_by_default_and_with_false(self):
        self.reading(self.node_a, 1)

        self.assertNotIn("merged", self.series(node_id="A", merge="false").data)

    def test_default_interval_is_the_last_24_hours(self):
        now_reading = SensorReading.objects.create(
            node=self.node_a, temperature=33, humidity=40, smoke=1, flame=False,
        )
        SensorReading.objects.create(
            node=self.node_a, temperature=99, humidity=40, smoke=1, flame=False,
            timestamp=now_reading.timestamp - timedelta(days=3),
        )

        response = self.client.get(reverse("reading_series"), {"node_id": "A"})

        self.assertEqual([p["value"] for p in response.data["series"][0]["points"]], [33])

    def test_invalid_parameters_are_rejected(self):
        cases = {
            "no node": {},
            "empty node": {"node_id": " , "},
            "too many nodes": {"node_id": ",".join(f"N{i}" for i in range(11))},
            "bad field": {"node_id": "A", "field": "pressure"},
            "bad from": {"node_id": "A", "from": "ayer"},
            "from after to": {"node_id": "A", "from": at(10).isoformat(), "to": at(1).isoformat()},
            "span too long": {"node_id": "A", "from": at(0).isoformat(),
                              "to": (BASE + timedelta(days=40)).isoformat()},
            "step text": {"node_id": "A", "step": "x"},
            "step zero": {"node_id": "A", "step": "0"},
            "step too big": {"node_id": "A", "step": "100000"},
            "too many buckets": {"node_id": "A", "step": "1"},
            "bad merge": {"node_id": "A", "merge": "quizá"},
        }
        for name, params in cases.items():
            with self.subTest(name):
                response = self.client.get(reverse("reading_series"), params)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_node_is_404(self):
        self.assertEqual(self.series(node_id="NO-EXISTE").status_code, status.HTTP_404_NOT_FOUND)

    def test_too_many_points_without_step_is_refused(self):
        for minute in range(4):
            self.reading(self.node_a, minute)

        with patch.object(series_queries, "MAX_POINTS", 3):
            response = self.series(node_id="A")
            with_step = self.series(node_id="A", step=300)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(with_step.status_code, status.HTTP_200_OK)

    @override_settings(PUBLIC_READ_ACCESS=False)
    def test_requires_authentication_when_reads_are_private(self):
        self.assertEqual(self.series(node_id="A").status_code, status.HTTP_401_UNAUTHORIZED)
