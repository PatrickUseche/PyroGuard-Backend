"""Pruebas del simulador IoT (simulador_iot.py, en la raíz del backend)."""
import io
import random
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

import simulador_iot as simulator
from api.services.risk_rules import SMOKE_FIRE, SMOKE_WARNING, TEMP_FIRE, TEMP_WARNING, evaluate_risk


def make_args(**overrides):
    values = dict(
        url="http://api.test/api/readings/", node="NODE-001", nodes=1, prefix="SIM-",
        interval=5.0, scenario="normal", api_key="clave", seed=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def parse(*argv):
    with patch.object(sys, "argv", ["simulador_iot.py", *argv]):
        return simulator.parse_args()


class ParseArgsTests(SimpleTestCase):
    def test_defaults(self):
        with patch.dict("os.environ", {"INGEST_API_KEY": "", "API_URL": ""}, clear=False):
            args = parse()

        self.assertEqual(
            (args.node, args.nodes, args.prefix, args.scenario, args.seed),
            ("NODE-001", 1, "SIM-", "random", None),
        )
        self.assertEqual(args.interval, 5)

    def test_all_options(self):
        args = parse("--node", "A", "--nodes", "3", "--prefix", "T-", "--interval", "0.5",
                     "--scenario", "fire", "--api-key", "k", "--seed", "7", "--url", "http://x/")

        self.assertEqual((args.node, args.nodes, args.prefix, args.interval), ("A", 3, "T-", 0.5))
        self.assertEqual((args.scenario, args.api_key, args.seed, args.url), ("fire", "k", 7, "http://x/"))

    def test_the_api_key_and_url_come_from_the_environment(self):
        with patch.dict("os.environ", {"INGEST_API_KEY": "del-entorno", "API_URL": "http://entorno/"}):
            args = parse()

        self.assertEqual((args.api_key, args.url), ("del-entorno", "http://entorno/"))

    def test_invalid_values_are_rejected(self):
        for argv in (["--interval", "0"], ["--interval", "-1"], ["--nodes", "0"], ["--nodes", "101"],
                     ["--scenario", "otro"], ["--nodes", "x"]):
            with self.subTest(argv=argv):
                with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                    parse(*argv)


class NodeIdsTests(SimpleTestCase):
    def test_one_node_uses_the_node_option(self):
        self.assertEqual(simulator.node_ids(make_args(node="MI-NODO")), ["MI-NODO"])

    def test_several_nodes_use_the_prefix_and_a_three_digit_number(self):
        self.assertEqual(simulator.node_ids(make_args(nodes=3)), ["SIM-001", "SIM-002", "SIM-003"])

    def test_a_custom_prefix(self):
        self.assertEqual(simulator.node_ids(make_args(nodes=2, prefix="BOSQUE-")), ["BOSQUE-001", "BOSQUE-002"])

    def test_the_node_option_is_ignored_with_several_nodes(self):
        self.assertNotIn("NODE-001", simulator.node_ids(make_args(nodes=2)))

    def test_a_hundred_nodes_have_unique_ids(self):
        ids = simulator.node_ids(make_args(nodes=100))

        self.assertEqual(len(set(ids)), 100)
        self.assertEqual(ids[-1], "SIM-100")


class GenerateDataTests(SimpleTestCase):
    def generate(self, scenario, count=200, seed=1):
        rng = random.Random(seed)
        return [simulator.generate_simulated_data("N", scenario, rng) for _ in range(count)]

    def test_the_payload_has_the_ingest_fields(self):
        payload, _ = simulator.generate_simulated_data("SIM-007", "normal", random.Random(1))

        self.assertEqual(set(payload), {"node_id", "temperature", "humidity", "smoke", "gas", "flame", "timestamp"})
        self.assertEqual(payload["node_id"], "SIM-007")
        self.assertTrue(payload["timestamp"].endswith("+00:00"))

    def test_the_normal_scenario_is_always_normal_for_the_rules(self):
        for payload, scenario in self.generate("normal"):
            self.assertEqual(scenario, "normal")
            self.assertFalse(payload["flame"])
            self.assertEqual(evaluate_risk(payload)["level"], "NORMAL")

    def test_the_warning_scenario_is_always_a_warning_for_the_rules(self):
        for payload, scenario in self.generate("warning"):
            self.assertEqual(scenario, "warning")
            self.assertEqual(evaluate_risk(payload)["level"], "WARNING")
            self.assertTrue(payload["temperature"] >= TEMP_WARNING or payload["smoke"] >= SMOKE_WARNING)

    def test_the_fire_scenario_is_always_fire_for_the_rules(self):
        for payload, scenario in self.generate("fire"):
            self.assertEqual(scenario, "fire")
            self.assertTrue(payload["flame"])
            self.assertGreaterEqual(payload["temperature"], TEMP_FIRE)
            self.assertGreaterEqual(payload["smoke"], SMOKE_FIRE)
            self.assertEqual(evaluate_risk(payload)["level"], "FIRE")

    def test_values_stay_inside_the_ingest_limits(self):
        for scenario in ("normal", "warning", "fire"):
            for payload, _ in self.generate(scenario):
                self.assertTrue(-50 <= payload["temperature"] <= 150)
                self.assertTrue(0 <= payload["humidity"] <= 100)
                self.assertGreaterEqual(payload["smoke"], 0)
                self.assertGreaterEqual(payload["gas"], 0)

    def test_random_mixes_the_scenarios_with_weights_85_10_5(self):
        counts = {"normal": 0, "warning": 0, "fire": 0}
        for _, scenario in self.generate("random", count=4000, seed=3):
            counts[scenario] += 1

        self.assertGreater(counts["normal"], counts["warning"] * 4)
        self.assertGreater(counts["warning"], counts["fire"])
        self.assertGreater(counts["fire"], 0)
        self.assertAlmostEqual(counts["normal"] / 4000, 0.85, delta=0.04)

    def test_the_same_seed_repeats_the_scenarios_and_values(self):
        def run(seed):
            return [
                ({k: v for k, v in payload.items() if k != "timestamp"}, scenario)
                for payload, scenario in self.generate("random", count=50, seed=seed)
            ]

        self.assertEqual(run(11), run(11))
        self.assertNotEqual(run(11), run(12))


class SendReadingTests(SimpleTestCase):
    def test_success_on_201(self):
        with patch("simulador_iot.requests.post", return_value=MagicMock(status_code=201)) as post:
            ok, message = simulator.send_reading("http://x/", {"a": 1}, {"X-API-Key": "k"})

        self.assertTrue(ok)
        self.assertEqual(message, "Envío exitoso.")
        post.assert_called_once_with("http://x/", json={"a": 1}, headers={"X-API-Key": "k"}, timeout=10)

    def test_an_http_error_is_reported_with_code_and_body(self):
        response = MagicMock(status_code=401, text="no autorizado")
        with patch("simulador_iot.requests.post", return_value=response):
            ok, message = simulator.send_reading("http://x/", {}, {})

        self.assertFalse(ok)
        self.assertIn("401", message)
        self.assertIn("no autorizado", message)

    def test_a_duplicate_answer_is_not_a_success(self):
        with patch("simulador_iot.requests.post", return_value=MagicMock(status_code=200, text="duplicate")):
            self.assertFalse(simulator.send_reading("http://x/", {}, {})[0])

    def test_a_network_error_does_not_raise(self):
        with patch("simulador_iot.requests.post", side_effect=requests.ConnectionError("rechazado")):
            ok, message = simulator.send_reading("http://x/", {}, {})

        self.assertFalse(ok)
        self.assertIn("No se pudo conectar", message)
        self.assertIn("rechazado", message)


class SendDataTests(SimpleTestCase):
    def run_simulator(self, args, max_rounds=2, post=None):
        sleeps = []
        output = io.StringIO()
        post = post or MagicMock(return_value=MagicMock(status_code=201))
        with patch("simulador_iot.requests.post", post), redirect_stdout(output):
            simulator.send_data(args, sleep=sleeps.append, max_rounds=max_rounds)
        return post, sleeps, output.getvalue()

    def test_one_reading_per_node_and_round(self):
        post, _, _ = self.run_simulator(make_args(nodes=3, scenario="normal", seed=1), max_rounds=2)

        sent = [call.kwargs["json"]["node_id"] for call in post.call_args_list]
        self.assertEqual(sent, ["SIM-001", "SIM-002", "SIM-003"] * 2)

    def test_it_waits_the_interval_after_each_round(self):
        _, sleeps, _ = self.run_simulator(make_args(interval=2.5), max_rounds=3)

        self.assertEqual(sleeps, [2.5, 2.5, 2.5])

    def test_the_api_key_goes_in_the_header(self):
        post, _, _ = self.run_simulator(make_args(api_key="secreta"), max_rounds=1)

        self.assertEqual(post.call_args.kwargs["headers"], {"X-API-Key": "secreta"})

    def test_without_an_api_key_no_header_is_sent_and_a_warning_is_printed(self):
        post, _, output = self.run_simulator(make_args(api_key=""), max_rounds=1)

        self.assertEqual(post.call_args.kwargs["headers"], {})
        self.assertIn("no se enviará X-API-Key", output)

    def test_the_output_lists_the_nodes_and_marks_readings_as_simulated(self):
        _, _, output = self.run_simulator(make_args(nodes=2, scenario="fire", seed=1), max_rounds=1)

        self.assertIn("SIM-001, SIM-002", output)
        self.assertIn("SIMULADO | escenario=fire nodo=SIM-001", output)
        self.assertIn("semilla 1", output)
        self.assertIn("Envío exitoso.", output)

    def test_the_same_seed_sends_the_same_values(self):
        def values(seed):
            post, _, _ = self.run_simulator(make_args(nodes=2, scenario="random", seed=seed), max_rounds=5)
            return [{k: v for k, v in c.kwargs["json"].items() if k != "timestamp"} for c in post.call_args_list]

        self.assertEqual(values(5), values(5))
        self.assertNotEqual(values(5), values(6))

    def test_it_keeps_going_when_the_server_fails(self):
        failing = MagicMock(side_effect=requests.ConnectionError("caído"))

        post, sleeps, output = self.run_simulator(make_args(nodes=2), max_rounds=2, post=failing)

        self.assertEqual(post.call_count, 4)
        self.assertEqual(len(sleeps), 2)
        self.assertIn("No se pudo conectar", output)

    def test_it_stops_cleanly_with_ctrl_c(self):
        output = io.StringIO()
        with patch("simulador_iot.requests.post", return_value=MagicMock(status_code=201)), redirect_stdout(output):
            simulator.send_data(make_args(), sleep=MagicMock(side_effect=KeyboardInterrupt))

        self.assertIn("Simulador detenido por el usuario.", output.getvalue())

    def test_zero_rounds_send_nothing(self):
        post, sleeps, _ = self.run_simulator(make_args(), max_rounds=0)

        post.assert_not_called()
        self.assertEqual(sleeps, [])
