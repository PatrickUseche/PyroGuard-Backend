"""Mide cada estructura de ``api/structures`` frente a la consulta equivalente en la base de datos.

Cada caso crea datos sintéticos, ejecuta la operación con la estructura y con la base, comprueba que
ambas dan el mismo resultado y mide cuánto tarda cada una. Todo ocurre dentro de una transacción que se
deshace al final, así que no deja datos en la base.
"""
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from django.db import transaction
from django.db.models import Avg, Max, Min, Q

from api.models import Node, NodeLink, SensorReading
from api.services.series import TimeSeries
from api.structures.adjacency_graph import AdjacencyGraph
from api.structures.disjoint_set_union import DisjointSetUnion
from api.structures.duplicate_bloom_filter import DuplicateBloomFilter
from api.structures.least_recently_used_cache import LeastRecentlyUsedCache
from api.structures.prefix_trie import PrefixTrie
from api.structures.priority_min_heap import PriorityMinHeap
from api.structures.recent_items_ring import RecentItemsRing
from api.structures.rolling_extremes_window import RollingExtremesWindow

WINDOW = 50
TOP_K = 10
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class Result:
    case: str
    structure: str
    size: int
    structure_us: float
    database_us: float

    @property
    def speedup(self):
        return self.database_us / self.structure_us if self.structure_us else float("inf")


@dataclass
class Case:
    name: str
    structure: str
    prepare: object  # prepare(context) -> (structure_op, database_op, same)


def _time(operation, repeat):
    """Microsegundos medios por llamada (la mejor de tres tandas, para filtrar ruido)."""
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        for _ in range(repeat):
            operation()
        best = min(best, (time.perf_counter() - started) / repeat)
    return best * 1_000_000


class Data:
    """Datos sintéticos compartidos por los casos de un tamaño."""

    def __init__(self, readings, rng):
        self.readings = readings
        self.rng = rng
        self.node_count = max(60, readings // 10)
        self.node = Node.objects.create(node_id="BENCH-MAIN", latitude=0.0)
        self.nodes = [self.node]
        extra = [
            Node(
                node_id=f"BENCH-{number:05d}",
                latitude=round(rng.uniform(-80, 80), 6),
            )
            for number in range(1, self.node_count)
        ]
        Node.objects.bulk_create(extra)
        others = Node.objects.filter(node_id__startswith="BENCH-0").exclude(pk=self.node.pk)
        self.nodes += list(others.order_by("node_id"))
        self.timestamps = [START + timedelta(minutes=minute) for minute in range(readings)]
        self.temperatures = [round(rng.uniform(10, 60), 2) for _ in range(readings)]
        SensorReading.objects.bulk_create(
            [
                SensorReading(
                    node=self.node, temperature=temperature, humidity=40, smoke=1, flame=False, timestamp=when,
                )
                for when, temperature in zip(self.timestamps, self.temperatures, strict=True)
            ],
            batch_size=500,
        )
        self.node_ids = [node.node_id for node in self.nodes]
        self.links = self._link_nodes()

    def _link_nodes(self):
        """Anillo más cuerdas: cada nodo tiene entre 2 y 4 vecinos."""
        count = len(self.nodes)
        pairs = set()
        for index in range(count):
            pairs.add(tuple(sorted((index, (index + 1) % count))))
            pairs.add(tuple(sorted((index, (index * 7 + 3) % count))))
        pairs = {pair for pair in pairs if pair[0] != pair[1]}
        NodeLink.objects.bulk_create(
            [NodeLink(node_a=self.nodes[a], node_b=self.nodes[b]) for a, b in sorted(pairs)], batch_size=500
        )
        return sorted(pairs)


# --- Casos --------------------------------------------------------------------------------

def last_readings(data):
    ring = RecentItemsRing(WINDOW)
    for temperature in data.temperatures[-WINDOW:]:
        ring.append(temperature)

    def structure():
        return list(reversed(list(ring)))

    def database():
        newest = SensorReading.objects.filter(node=data.node).order_by("-timestamp")
        return list(newest.values_list("temperature", flat=True)[:WINDOW])

    return structure, database, lambda a, b: a == b


def window_extremes(data):
    window = RollingExtremesWindow(WINDOW)
    for temperature in data.temperatures:
        window.push(temperature)
    recent = SensorReading.objects.filter(node=data.node).order_by("-timestamp").values("pk")[:WINDOW]

    def structure():
        return window.maximum, window.minimum

    def database():
        row = SensorReading.objects.filter(pk__in=recent).aggregate(high=Max("temperature"), low=Min("temperature"))
        return row["high"], row["low"]

    return structure, database, lambda a, b: a == b


def node_status_cache(data):
    cache = LeastRecentlyUsedCache(256)
    lookup = data.node.node_id
    cache.put(lookup, ("estado", data.node.pk))

    def structure():
        return cache.get(lookup)[1]

    def database():
        node = Node.objects.get(node_id=lookup)
        SensorReading.objects.filter(node=node).order_by("-timestamp").first()
        return node.pk

    return structure, database, lambda a, b: a == b


def duplicate_check(data):
    bloom = DuplicateBloomFilter(max(data.readings, 100), 0.01)
    for when in data.timestamps:
        bloom.add((data.node.node_id, when.isoformat()))
    present = (data.node.node_id, data.timestamps[data.readings // 2].isoformat())
    present_at = data.timestamps[data.readings // 2]

    def structure():
        return present in bloom

    def database():
        return SensorReading.objects.filter(node=data.node, timestamp=present_at).exists()

    return structure, database, lambda a, b: a is True and b is True


def prefix_search(data):
    trie = PrefixTrie()
    for node_id in data.node_ids:
        trie.insert(node_id)
    prefix = "BENCH-001"

    def structure():
        return trie.with_prefix(prefix, limit=20)

    def database():
        return list(
            Node.objects.filter(node_id__istartswith=prefix).order_by("node_id").values_list("node_id", flat=True)[:20]
        )

    return structure, database, lambda a, b: a == b


def top_risk(data):
    rows = [(node.node_id, node.latitude or 0.0) for node in data.nodes]

    def structure():
        heap = PriorityMinHeap.from_items(rows, priority=lambda row: (-row[1], row[0]))
        return [row[0] for row in (heap.pop() for _ in range(TOP_K))]

    def database():
        return list(Node.objects.order_by("-latitude", "node_id").values_list("node_id", flat=True)[:TOP_K])

    return structure, database, lambda a, b: a == b


def _database_bfs(start, hops):
    """El recorrido por saltos hecho con consultas: una por cada nodo del frente."""
    seen = {start: 0}
    frontier = [start]
    for depth in range(1, hops + 1):
        following = []
        for node_id in frontier:
            neighbors = NodeLink.objects.filter(Q(node_a__node_id=node_id) | Q(node_b__node_id=node_id)).values_list(
                "node_a__node_id", "node_b__node_id"
            )
            for first, second in neighbors:
                other = second if first == node_id else first
                if other not in seen:
                    seen[other] = depth
                    following.append(other)
        frontier = following
    del seen[start]
    return seen


def neighbors_by_hops(data):
    graph = AdjacencyGraph()
    for first, second in data.links:
        graph.add_edge(data.node_ids[first], data.node_ids[second])
    start = data.node_ids[len(data.node_ids) // 2]

    def structure():
        return graph.reachable_within(start, 2)

    def database():
        return _database_bfs(start, 2)

    return structure, database, lambda a, b: a == b


def risk_zones(data):
    risky = set(data.node_ids[::3])
    graph = AdjacencyGraph()
    for first, second in data.links:
        graph.add_edge(data.node_ids[first], data.node_ids[second])

    def structure():
        sets = DisjointSetUnion(sorted(risky))
        for node_id in risky:
            for neighbor in graph.neighbors(node_id):
                if neighbor in risky:
                    sets.union(node_id, neighbor)
        return sorted(sorted(group) for group in sets.groups())

    def database():
        # Sin Union-Find: se recorre desde cada nodo en riesgo, preguntando a la base por sus vecinos.
        remaining, groups = set(risky), []
        while remaining:
            start = min(remaining)
            group, frontier = {start}, [start]
            while frontier:
                node_id = frontier.pop()
                rows = NodeLink.objects.filter(Q(node_a__node_id=node_id) | Q(node_b__node_id=node_id)).values_list(
                    "node_a__node_id", "node_b__node_id"
                )
                for first, second in rows:
                    other = second if first == node_id else first
                    if other in risky and other not in group:
                        group.add(other)
                        frontier.append(other)
            remaining -= group
            groups.append(sorted(group))
        return sorted(groups)

    return structure, database, lambda a, b: a == b


def range_average(data):
    series = TimeSeries(zip(data.timestamps, data.temperatures, strict=True))
    start = data.timestamps[data.readings // 4]
    end = data.timestamps[(data.readings * 3) // 4]

    def structure():
        return series.mean_between(start, end)

    def database():
        return SensorReading.objects.filter(
            node=data.node, timestamp__gte=start, timestamp__lte=end
        ).aggregate(mean=Avg("temperature"))["mean"]

    return structure, database, lambda a, b: abs(a - b) < 1e-6


CASES = [
    Case("Últimas 50 lecturas de un nodo", "RecentItemsRing", last_readings),
    Case("Máximo y mínimo de las últimas 50", "RollingExtremesWindow", window_extremes),
    Case("Estado de un nodo (acierto de caché)", "LeastRecentlyUsedCache", node_status_cache),
    Case("¿Lectura duplicada?", "DuplicateBloomFilter", duplicate_check),
    Case("Buscar nodos por prefijo", "PrefixTrie", prefix_search),
    Case("Los 10 nodos de mayor riesgo", "PriorityMinHeap", top_risk),
    Case("Vecinos a 2 saltos", "AdjacencyGraph + BFS", neighbors_by_hops),
    Case("Zonas de riesgo", "DisjointSetUnion", risk_zones),
    Case("Promedio de un intervalo de tiempo", "TimeSeries (búsqueda binaria + PrefixSums)", range_average),
]


class _Rollback(Exception):
    pass


def run_benchmarks(sizes, repeat=200, db_repeat=20, seed=1, cases=None):
    """Ejecuta los casos para cada tamaño y devuelve una lista de ``Result``.

    Lanza ``AssertionError`` si la estructura y la base no coinciden en algún caso: una medición de algo
    que da un resultado distinto no sirve.
    """
    results = []
    selected = cases or CASES
    for size in sizes:
        try:
            with transaction.atomic():
                data = Data(size, random.Random(seed))
                for case in selected:
                    structure, database, same = case.prepare(data)
                    expected, found = database(), structure()
                    assert same(found, expected), (
                        f"'{case.name}' ({size}): la estructura y la base no coinciden: {found!r} != {expected!r}"
                    )
                    structure_us = _time(structure, repeat)
                    database_us = _time(database, db_repeat)
                    results.append(
                        Result(case.name, case.structure, size, structure_us, database_us)
                    )
                raise _Rollback
        except _Rollback:
            pass
    return results


def format_table(results, markdown=False):
    """Texto con una fila por caso y tamaño."""
    header = ("Caso", "Estructura", "Lecturas", "Estructura (µs)", "Base de datos (µs)", "Veces más rápida")
    rows = [
        (r.case, r.structure, f"{r.size:,}", f"{r.structure_us:,.1f}", f"{r.database_us:,.1f}", f"{r.speedup:,.0f}x")
        for r in results
    ]
    if markdown:
        lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
        lines += ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join(lines)
    widths = [max(len(str(item)) for item in column) for column in zip(header, *rows, strict=True)]
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    lines = [fmt.format(*header), fmt.format(*("-" * width for width in widths))]
    lines += [fmt.format(*row) for row in rows]
    return "\n".join(lines)
