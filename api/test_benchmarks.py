"""Pruebas de benchmark_structures: que mida lo mismo en la estructura y en la base, sin dejar datos."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from api.benchmarks import CASES, Case, Result, format_table, run_benchmarks

from .models import Node, NodeLink, SensorReading


def quick(**kwargs):
    return run_benchmarks([150], repeat=2, db_repeat=1, **kwargs)


class RunBenchmarksTests(TestCase):
    def test_every_case_is_measured_for_every_size(self):
        results = run_benchmarks([120, 200], repeat=2, db_repeat=1)

        self.assertEqual(len(results), 2 * len(CASES))
        self.assertEqual({r.size for r in results}, {120, 200})
        self.assertEqual([r.case for r in results[: len(CASES)]], [case.name for case in CASES])

    def test_structure_and_database_agree_in_every_case(self):
        # run_benchmarks lanza AssertionError si alguna estructura difiere de su consulta equivalente.
        self.assertEqual(len(quick()), len(CASES))

    def test_every_measurement_is_positive(self):
        for result in quick():
            with self.subTest(case=result.case):
                self.assertGreater(result.structure_us, 0)
                self.assertGreater(result.database_us, 0)
                self.assertGreater(result.speedup, 0)

    def test_no_data_is_left_in_the_database(self):
        quick()

        self.assertEqual(Node.objects.count(), 0)
        self.assertEqual(SensorReading.objects.count(), 0)
        self.assertEqual(NodeLink.objects.count(), 0)

    def test_data_already_in_the_database_is_untouched(self):
        existing = Node.objects.create(node_id="REAL-1")

        quick()

        self.assertEqual(list(Node.objects.all()), [existing])

    def test_results_are_repeatable_with_the_same_seed(self):
        first = [(r.case, r.size) for r in quick(seed=5)]
        second = [(r.case, r.size) for r in quick(seed=5)]

        self.assertEqual(first, second)

    def test_a_mismatch_between_structure_and_database_is_reported(self):
        def broken(data):
            return (lambda: 1), (lambda: 2), (lambda a, b: a == b)

        with self.assertRaises(AssertionError) as raised:
            run_benchmarks([120], repeat=1, db_repeat=1, cases=[Case("Caso roto", "Nada", broken)])

        self.assertIn("Caso roto", str(raised.exception))

    def test_the_structures_beat_the_database_where_the_gap_is_large(self):
        by_case = {r.case: r for r in run_benchmarks([400], repeat=20, db_repeat=3)}

        for name in ("Estado de un nodo (acierto de caché)", "Máximo y mínimo de las últimas 50"):
            with self.subTest(case=name):
                self.assertGreater(by_case[name].speedup, 2)


class FormatTableTests(TestCase):
    RESULTS = [
        Result("Caso uno", "Estructura A", 1000, 2.0, 400.0),
        Result("Caso dos", "Estructura B", 10000, 0.5, 100.0),
    ]

    def test_plain_table_has_a_header_and_one_row_per_result(self):
        lines = format_table(self.RESULTS).splitlines()

        self.assertEqual(len(lines), 4)
        self.assertIn("Estructura (µs)", lines[0])
        self.assertIn("200x", lines[2])
        self.assertIn("10,000", lines[3])

    def test_markdown_table(self):
        lines = format_table(self.RESULTS, markdown=True).splitlines()

        self.assertTrue(lines[0].startswith("| Caso | Estructura |"))
        self.assertEqual(lines[1], "|---|---|---|---|---|---|")
        self.assertEqual(len(lines), 4)
        self.assertIn("| Caso uno | Estructura A | 1,000 | 2.0 | 400.0 | 200x |", lines[2])

    def test_a_structure_slower_than_the_database_shows_a_decimal_speedup(self):
        slow = Result("x", "y", 1, 10.0, 4.0)

        self.assertEqual(slow.speedup_text, "0.4x")
        self.assertEqual(Result("x", "y", 1, 1.0, 12.0).speedup_text, "12x")
        self.assertEqual(Result("x", "y", 1, 1.0, 1500.0).speedup_text, "1,500x")

    def test_speedup_is_database_over_structure(self):
        self.assertEqual(self.RESULTS[0].speedup, 200)
        self.assertEqual(Result("x", "y", 1, 0.0, 5.0).speedup, float("inf"))


class BenchmarkCommandTests(TestCase):
    def run_command(self, *args):
        out, err = StringIO(), StringIO()
        call_command("benchmark_structures", *args, stdout=out, stderr=err)
        return out.getvalue()

    def test_prints_a_table_with_every_case(self):
        output = self.run_command("--sizes", "120", "--repeat", "2", "--db-repeat", "1")

        for case in CASES:
            self.assertIn(case.name, output)
            self.assertIn(case.structure, output)

    def test_markdown_option(self):
        output = self.run_command("--sizes", "120", "--repeat", "2", "--db-repeat", "1", "--markdown")

        self.assertTrue(output.startswith("| Caso |"))

    def test_several_sizes(self):
        output = self.run_command("--sizes", "120,150", "--repeat", "1", "--db-repeat", "1")

        self.assertIn("120", output)
        self.assertIn("150", output)

    def test_invalid_options_are_rejected(self):
        for args in (["--sizes", "abc"], ["--sizes", "50"], ["--sizes", ""], ["--repeat", "0"],
                     ["--db-repeat", "0"]):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.run_command(*args)

    def test_leaves_no_data_behind(self):
        self.run_command("--sizes", "120", "--repeat", "1", "--db-repeat", "1")

        self.assertEqual(Node.objects.count(), 0)
