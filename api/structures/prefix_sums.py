class PrefixSums:
    """Sumas de prefijos: la suma o el promedio de cualquier rango en O(1).

    Guarda ``totals[i]`` = suma de los primeros ``i`` valores, así que la suma del
    rango ``[start, stop)`` es ``totals[stop] - totals[start]`` sin recorrerlo.
    Los rangos usan la convención de ``range`` y de las rebanadas de Python:
    ``start`` incluido y ``stop`` excluido. Se pueden seguir agregando valores al
    final (por ejemplo, las lecturas nuevas de un sensor).

    Con valores ``float`` la resta de totales acumula error de redondeo; para
    enteros o ``Decimal`` el resultado es exacto.

    Complejidad (``n`` = valores guardados):
        PrefixSums(values) -- O(n)
        append(value) -- O(1)
        range_sum(start, stop) / range_mean(start, stop) -- O(1)
        total() / len() -- O(1)
        espacio -- O(n)
    """

    def __init__(self, values=()):
        self._totals = [0]
        for value in values:
            self.append(value)

    def __len__(self):
        return len(self._totals) - 1

    def append(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Solo se admiten números.")
        if value != value:  # NaN contaminaría todas las sumas siguientes
            raise ValueError("No se admite NaN.")
        self._totals.append(self._totals[-1] + value)

    def total(self):
        return self._totals[-1]

    def _check_range(self, start, stop):
        for bound in (start, stop):
            if not isinstance(bound, int) or isinstance(bound, bool):
                raise TypeError("Los límites del rango deben ser enteros.")
        if not 0 <= start <= stop <= len(self):
            raise IndexError("Rango fuera de los valores guardados.")

    def range_sum(self, start, stop):
        """Suma de los valores en las posiciones ``start`` hasta ``stop - 1``."""
        self._check_range(start, stop)
        return self._totals[stop] - self._totals[start]

    def range_mean(self, start, stop):
        """Promedio del rango; falla con ``ValueError`` si el rango está vacío."""
        self._check_range(start, stop)
        if start == stop:
            raise ValueError("No hay promedio de un rango vacío.")
        return (self._totals[stop] - self._totals[start]) / (stop - start)
