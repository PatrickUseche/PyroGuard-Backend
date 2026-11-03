"""Pruebas de los agregados por hora (ReadingHourly y aggregate_readings)."""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Node, ReadingHourly, SensorReading


def at(hour, minute=0):
    return datetime(2026, 10, 30, hour, minute, tzinfo=dt_timezone.utc)


class AggregateReadingsTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(node_id="NODE-001")
        self.other = Node.objects.create(node_id="NODE-002")

    def reading(self, when, temperature=20.0, humidity=40.0, smoke=1.0, flame=False, node=None):
        return SensorReading.objects.create(
            node=node or self.node, temperature=temperature, humidity=humidity,
            smoke=smoke, flame=flame, timestamp=when,
        )

    def aggregate(self, **options):
        out = StringIO()
        call_command("aggregate_readings", stdout=out, **options)
        return out.getvalue()

    def test_summarises_each_node_and_hour(self):
        self.reading(at(10, 5), temperature=20, humidity=30, smoke=5)
        self.reading(at(10, 25), temperature=30, humidity=50, smoke=9, flame=True)
        self.reading(at(10, 55), temperature=40, humidity=40, smoke=2, flame=True)

        self.aggregate()

        row = ReadingHourly.objects.get()
        self.assertEqual(row.node, self.node)
        self.assertEqual(row.hour, at(10))
        self.assertEqual(row.reading_count, 3)
        self.assertEqual(row.temperature_min, 20)
        self.assertEqual(row.temperature_avg, 30)
        self.assertEqual(row.temperature_max, 40)
        self.assertEqual(row.humidity_avg, 40)
        self.assertEqual(row.smoke_max, 9)
        self.assertEqual(row.flame_count, 2)

    def test_each_hour_and_node_gets_its_own_row(self):
        self.reading(at(10, 10))
        self.reading(at(11, 10))
        self.reading(at(11, 20), node=self.other)

        output = self.aggregate()

        self.assertEqual(ReadingHourly.objects.count(), 3)
        self.assertIn("Se resumieron 3 hora(s)", output)
        self.assertEqual(
            list(ReadingHourly.objects.filter(node=self.node).values_list("hour", flat=True)),
            [at(10), at(11)],
        )

    def test_the_hour_boundary_belongs_to_the_next_hour(self):
        self.reading(at(10, 59))
        self.reading(at(11, 0))

        self.aggregate()

        self.assertEqual(ReadingHourly.objects.get(hour=at(10)).reading_count, 1)
        self.assertEqual(ReadingHourly.objects.get(hour=at(11)).reading_count, 1)

    def test_running_it_twice_does_not_duplicate_rows(self):
        self.reading(at(10, 5))
        self.reading(at(11, 5))

        self.aggregate()
        self.aggregate()

        self.assertEqual(ReadingHourly.objects.count(), 2)

    def test_the_last_hour_is_recalculated_when_more_readings_arrive(self):
        self.reading(at(10, 5), temperature=20)
        self.aggregate()
        self.reading(at(10, 50), temperature=40)

        self.aggregate()

        row = ReadingHourly.objects.get()
        self.assertEqual(row.reading_count, 2)
        self.assertEqual(row.temperature_avg, 30)

    def test_completed_hours_are_left_alone_by_default(self):
        self.reading(at(9, 5), temperature=20)
        self.reading(at(10, 5), temperature=20)
        self.aggregate()
        ReadingHourly.objects.filter(hour=at(9)).update(reading_count=99)

        self.aggregate()

        self.assertEqual(ReadingHourly.objects.get(hour=at(9)).reading_count, 99)

    def test_all_recalculates_every_hour(self):
        self.reading(at(9, 5))
        self.aggregate()
        ReadingHourly.objects.update(reading_count=99)

        self.aggregate(all=True)

        self.assertEqual(ReadingHourly.objects.get().reading_count, 1)

    def test_summaries_survive_the_purge_of_their_readings(self):
        old = self.reading(at(10, 5))
        self.aggregate()

        old.delete()

        self.assertEqual(ReadingHourly.objects.get().reading_count, 1)

    def test_without_readings_nothing_is_created(self):
        output = self.aggregate()

        self.assertEqual(ReadingHourly.objects.count(), 0)
        self.assertIn("Se resumieron 0 hora(s)", output)

    def test_a_node_and_hour_cannot_be_stored_twice(self):
        values = dict(
            node=self.node, hour=at(10), reading_count=1, temperature_min=1, temperature_avg=1,
            temperature_max=1, humidity_avg=1, smoke_max=1,
        )
        ReadingHourly.objects.create(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ReadingHourly.objects.create(**values)

    def test_deleting_a_node_deletes_its_summaries(self):
        self.reading(at(10, 5))
        self.aggregate()

        self.node.delete()

        self.assertEqual(ReadingHourly.objects.count(), 0)

    def test_string_representation(self):
        self.reading(at(10, 5))
        self.aggregate()

        self.assertEqual(str(ReadingHourly.objects.get()), "NODE-001 - 2026-10-30 10:00")

    def test_matches_a_direct_computation_on_many_readings(self):
        base = at(0)
        values = []
        for minute in range(0, 600, 7):
            temperature = 15 + (minute * 13) % 40
            values.append((base + timedelta(minutes=minute), temperature))
            self.reading(base + timedelta(minutes=minute), temperature=temperature)

        self.aggregate()

        for row in ReadingHourly.objects.all():
            in_hour = [t for when, t in values if row.hour <= when < row.hour + timedelta(hours=1)]
            self.assertEqual(row.reading_count, len(in_hour))
            self.assertEqual(row.temperature_min, min(in_hour))
            self.assertEqual(row.temperature_max, max(in_hour))
            self.assertAlmostEqual(row.temperature_avg, sum(in_hour) / len(in_hour))
