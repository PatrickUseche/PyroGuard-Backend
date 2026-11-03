"""Series temporales de lecturas: rangos por búsqueda binaria y promedios con sumas de prefijos.

Una ``TimeSeries`` guarda las marcas de tiempo (ordenadas) y los valores de un nodo.
Para cualquier intervalo de tiempo:

* la búsqueda binaria localiza dónde empieza y dónde termina en O(log n);
* las sumas de prefijos dan la suma y el promedio de ese tramo en O(1).

Así, una serie con ``b`` tramos (por ejemplo, un punto cada 5 minutos) se resume en
O(n + b log n) en lugar de recorrer los datos una vez por tramo (O(n · b)).
"""
from datetime import datetime, timedelta, timezone

from api.structures.prefix_sums import PrefixSums

MAX_BUCKETS = 2000


def lower_bound(sorted_values, target):
    """Primer índice cuyo valor es >= ``target``: O(log n)."""
    low, high = 0, len(sorted_values)
    while low < high:
        middle = (low + high) // 2
        if sorted_values[middle] < target:
            low = middle + 1
        else:
            high = middle
    return low


def upper_bound(sorted_values, target):
    """Primer índice cuyo valor es > ``target``: O(log n)."""
    low, high = 0, len(sorted_values)
    while low < high:
        middle = (low + high) // 2
        if sorted_values[middle] <= target:
            low = middle + 1
        else:
            high = middle
    return low


class TimeSeries:
    """Valores con su marca de tiempo, ordenados de más antiguo a más nuevo.

    Complejidad (``n`` = puntos, ``b`` = tramos):
        TimeSeries(points) -- O(n)
        index_range(start, end) -- O(log n)
        mean_between(start, end) -- O(log n)
        points_between(start, end) -- O(log n + k) con k = puntos devueltos
        buckets(start, end, step) -- O(b log n)
    """

    def __init__(self, points):
        """``points`` es un iterable de ``(timestamp, value)`` ya ordenado por tiempo."""
        self._timestamps = []
        self._sums = PrefixSums()
        self._values = []
        for timestamp, value in points:
            if self._timestamps and timestamp < self._timestamps[-1]:
                raise ValueError("Los puntos deben llegar ordenados por tiempo.")
            self._timestamps.append(timestamp)
            self._values.append(value)
            self._sums.append(value)

    def __len__(self):
        return len(self._timestamps)

    def index_range(self, start=None, end=None):
        """Posiciones ``[first, stop)`` de los puntos con ``start <= t <= end``."""
        first = 0 if start is None else lower_bound(self._timestamps, start)
        stop = len(self) if end is None else upper_bound(self._timestamps, end)
        return first, max(first, stop)

    def mean_between(self, start=None, end=None):
        """Promedio de los valores entre ``start`` y ``end`` (ambos incluidos), o ``None``."""
        first, stop = self.index_range(start, end)
        if first == stop:
            return None
        return self._sums.range_mean(first, stop)

    def points_between(self, start=None, end=None):
        first, stop = self.index_range(start, end)
        return list(zip(self._timestamps[first:stop], self._values[first:stop]))

    def buckets(self, start, end, step_seconds):
        """Promedio por tramos de ``step_seconds`` alineados al reloj (UTC).

        Devuelve ``[{"start", "count", "average"}]`` solo con los tramos que tienen
        datos. Falla con ``ValueError`` si el intervalo necesitaría más de
        ``MAX_BUCKETS`` tramos.
        """
        if step_seconds < 1:
            raise ValueError("El tramo debe durar al menos un segundo.")
        step = timedelta(seconds=step_seconds)
        origin = datetime(1970, 1, 1, tzinfo=timezone.utc)
        first_start = origin + step * ((start - origin) // step)
        if (end - first_start) / step > MAX_BUCKETS:
            raise ValueError(f"El intervalo necesita más de {MAX_BUCKETS} tramos.")

        buckets = []
        bucket_start = first_start
        while bucket_start <= end:
            bucket_end = bucket_start + step
            first = lower_bound(self._timestamps, max(bucket_start, start))
            stop = lower_bound(self._timestamps, min(bucket_end, end + timedelta.resolution))
            if stop > first:
                buckets.append(
                    {
                        "start": bucket_start,
                        "count": stop - first,
                        "average": self._sums.range_mean(first, stop),
                    }
                )
            bucket_start = bucket_end
        return buckets
