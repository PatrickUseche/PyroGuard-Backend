import hashlib
import math


class DuplicateBloomFilter:
    """Filtro de Bloom para saber, sin guardar los elementos, si ya se vieron.

    Es un arreglo de ``m`` bits y ``k`` funciones de dispersión. Agregar un elemento
    enciende ``k`` bits; consultarlo mira si esos ``k`` bits están encendidos.

    * Si responde **no**, el elemento seguro no se agregó (no hay falsos negativos).
    * Si responde **sí**, *probablemente* se agregó: puede ser un falso positivo,
      con probabilidad cercana a ``false_positive_rate`` mientras no se pase de
      ``expected_items`` elementos. Por eso un «sí» debe confirmarse en la fuente de
      verdad (por ejemplo, la base de datos) antes de descartar algo.

    No se pueden borrar elementos. Los elementos se convierten a bytes (``bytes``
    tal cual, el resto con ``repr``), así que ``1`` y ``"1"`` son distintos.
    Las ``k`` posiciones salen de un solo hash BLAKE2b con doble dispersión
    (``h1 + i * h2``), sin necesidad de ``k`` funciones independientes.

    Dimensionado (``n`` = expected_items, ``p`` = false_positive_rate):
        m = ceil(-n ln p / (ln 2)^2) bits,  k = round(m / n * ln 2) funciones

    Complejidad (``k`` es una constante pequeña que depende solo de ``p``):
        add(item) / item in filtro -- O(k) = O(1)
        estimated_false_positive_rate() -- O(1)
        espacio -- O(m) bits, independiente de cuántos elementos se agreguen
    """

    def __init__(self, expected_items, false_positive_rate=0.01):
        if not isinstance(expected_items, int) or isinstance(expected_items, bool) or expected_items < 1:
            raise ValueError("expected_items debe ser un entero mayor o igual que 1.")
        if (
            not isinstance(false_positive_rate, (int, float))
            or isinstance(false_positive_rate, bool)
            or not 0 < false_positive_rate < 1
        ):
            raise ValueError("false_positive_rate debe estar entre 0 y 1, sin incluirlos.")
        self._bit_count = max(
            8, math.ceil(-expected_items * math.log(false_positive_rate) / math.log(2) ** 2)
        )
        self._hash_count = max(1, round(self._bit_count / expected_items * math.log(2)))
        self._bits = bytearray((self._bit_count + 7) // 8)
        self._added = 0

    @property
    def bit_count(self):
        return self._bit_count

    @property
    def hash_count(self):
        return self._hash_count

    def __len__(self):
        """Cuántas veces se llamó a ``add`` con un elemento que parecía nuevo."""
        return self._added

    def _positions(self, item):
        data = item if isinstance(item, bytes) else repr(item).encode("utf-8")
        digest = hashlib.blake2b(data, digest_size=16).digest()
        first = int.from_bytes(digest[:8], "big")
        second = int.from_bytes(digest[8:], "big") | 1  # impar: recorre todas las posiciones
        return [(first + step * second) % self._bit_count for step in range(self._hash_count)]

    def add(self, item):
        """Agrega ``item``; devuelve ``True`` si parecía nuevo y ``False`` si ya parecía estar."""
        positions = self._positions(item)
        seen = True
        for position in positions:
            byte, mask = position >> 3, 1 << (position & 7)
            if not self._bits[byte] & mask:
                seen = False
                self._bits[byte] |= mask
        if not seen:
            self._added += 1
        return not seen

    def __contains__(self, item):
        return all(self._bits[position >> 3] & (1 << (position & 7)) for position in self._positions(item))

    def estimated_false_positive_rate(self):
        """Probabilidad actual de falso positivo según los elementos agregados."""
        return (1 - math.exp(-self._hash_count * self._added / self._bit_count)) ** self._hash_count
