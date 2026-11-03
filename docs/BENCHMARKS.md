# Medición de las estructuras de datos

Este informe compara cada estructura de `api/structures/` con la consulta equivalente en la base de datos y
contrasta la complejidad teórica con la observada. Lo genera `python manage.py benchmark_structures`
(ver README); antes de medir, el comando comprueba que estructura y base **devuelven el mismo resultado**.

## Cómo se midió

- **Entorno:** Windows 11, Python 3.13, SQLite en un archivo local, una sola conexión y un solo proceso.
  Es el entorno de desarrollo; en producción la base (PostgreSQL por red) suma latencia a cada consulta, así
  que las ventajas de la memoria serían **mayores**, no menores.
- **Datos sintéticos** (semilla 1): un nodo principal con 1 000, 10 000 y 50 000 lecturas (una por minuto) y
  `lecturas / 10` nodos más (100, 1 000 y 5 000), unidos en un anillo con cuerdas (2 a 4 vecinos por nodo).
- **Método:** cada operación se repite 100 veces (la estructura) o 3 veces (la consulta) y se toma la mejor de
  tres tandas; el tiempo es el promedio por llamada en microsegundos. Las estructuras ya están cargadas en memoria,
  como en el servidor tras la primera consulta; **el costo de cargarlas (una vez por worker) no está incluido**.
- Todo ocurre en una transacción que se deshace.

## Resultados

| Caso | Estructura | Lecturas | Estructura (µs) | Base de datos (µs) | Veces más rápida |
|---|---|---|---|---|---|
| Últimas 50 lecturas de un nodo | RecentItemsRing | 1,000 | 8.8 | 537.5 | 61x |
| Máximo y mínimo de las últimas 50 | RollingExtremesWindow | 1,000 | 0.6 | 970.3 | 1,502x |
| Estado de un nodo (acierto de caché) | LeastRecentlyUsedCache | 1,000 | 0.7 | 1,171.1 | 1,748x |
| ¿Lectura duplicada? | DuplicateBloomFilter | 1,000 | 6.1 | 487.3 | 80x |
| Buscar nodos por prefijo | PrefixTrie | 1,000 | 1.6 | 400.5 | 258x |
| Los 10 nodos de mayor riesgo | PriorityMinHeap | 1,000 | 153.7 | 676.6 | 4.4x |
| Vecinos a 2 saltos | AdjacencyGraph + BFS | 1,000 | 23.0 | 4,254.0 | 185x |
| Zonas de riesgo | DisjointSetUnion | 1,000 | 88.6 | 28,745.4 | 324x |
| Promedio de un intervalo de tiempo | TimeSeries (búsqueda binaria + PrefixSums) | 1,000 | 5.7 | 1,178.1 | 206x |
| Últimas 50 lecturas de un nodo | RecentItemsRing | 10,000 | 11.0 | 582.6 | 53x |
| Máximo y mínimo de las últimas 50 | RollingExtremesWindow | 10,000 | 0.7 | 934.6 | 1,397x |
| Estado de un nodo (acierto de caché) | LeastRecentlyUsedCache | 10,000 | 0.7 | 1,086.2 | 1,494x |
| ¿Lectura duplicada? | DuplicateBloomFilter | 10,000 | 11.6 | 426.4 | 37x |
| Buscar nodos por prefijo | PrefixTrie | 10,000 | 16.5 | 534.1 | 32x |
| Los 10 nodos de mayor riesgo | PriorityMinHeap | 10,000 | 1,554.0 | 703.7 | 0.5x |
| Vecinos a 2 saltos | AdjacencyGraph + BFS | 10,000 | 17.1 | 7,822.1 | 456x |
| Zonas de riesgo | DisjointSetUnion | 10,000 | 1,184.6 | 567,601.7 | 479x |
| Promedio de un intervalo de tiempo | TimeSeries (búsqueda binaria + PrefixSums) | 10,000 | 6.6 | 2,289.0 | 345x |
| Últimas 50 lecturas de un nodo | RecentItemsRing | 50,000 | 8.9 | 589.3 | 66x |
| Máximo y mínimo de las últimas 50 | RollingExtremesWindow | 50,000 | 0.6 | 1,063.6 | 1,735x |
| Estado de un nodo (acierto de caché) | LeastRecentlyUsedCache | 50,000 | 0.5 | 1,008.6 | 1,910x |
| ¿Lectura duplicada? | DuplicateBloomFilter | 50,000 | 7.8 | 495.8 | 64x |
| Buscar nodos por prefijo | PrefixTrie | 50,000 | 15.6 | 487.4 | 31x |
| Los 10 nodos de mayor riesgo | PriorityMinHeap | 50,000 | 10,905.0 | 1,470.6 | 0.1x |
| Vecinos a 2 saltos | AdjacencyGraph + BFS | 50,000 | 20.9 | 34,512.5 | 1,649x |
| Zonas de riesgo | DisjointSetUnion | 50,000 | 7,156.0 | 12,394,339.7 | 1,732x |
| Promedio de un intervalo de tiempo | TimeSeries (búsqueda binaria + PrefixSums) | 50,000 | 6.6 | 14,737.6 | 2,232x |

"Veces más rápida" es base de datos / estructura; por debajo de 1 la estructura pierde.

## Qué se ve

| Caso | Teoría | Observado de 1 000 a 50 000 lecturas |
| --- | --- | --- |
| `RecentItemsRing` | lectura O(k) en el tamaño del buffer, independiente de n | ~9 µs siempre: constante |
| `RollingExtremesWindow` | máximo y mínimo en O(1) | 0,6 µs siempre; la base pasa de 0,97 a 1,06 ms |
| `LeastRecentlyUsedCache` | acierto en O(1) | 0,5-0,7 µs siempre: sin consultas |
| `DuplicateBloomFilter` | O(k) con k constante | 6-12 µs: constante (ruido de medición) |
| `PrefixTrie` | O(m + resultados) | sube de 1,6 a ~16 µs y se **estabiliza**: el límite de 20 resultados acota el trabajo |
| `PriorityMinHeap` (top-K) | O(n + k log n) | crece **linealmente** con los nodos (154 µs → 1,6 ms → 10,9 ms) |
| `AdjacencyGraph` + BFS | O(V + E) del vecindario, no de todo el grafo | ~20 µs siempre; la base crece de 4 a 35 ms |
| `DisjointSetUnion` | O((V + E) α(V)) | **lineal** en los nodos en riesgo (≈ 2,6 a 4,3 µs por nodo) |
| `TimeSeries` (binaria + prefijos) | O(log n) | 5,7 → 6,6 µs: **plano**; la base pasa de 1,2 a 14,7 ms (crece con las filas del intervalo) |

La teoría se cumple: lo que prometía O(1) o O(log n) no crece con los datos, mientras la consulta equivalente
crece con el tamaño de la tabla o del intervalo. En los casos que repiten consultas (BFS por saltos, zonas) la
diferencia es de **hasta cuatro órdenes de magnitud** (12 s frente a 7 ms para las zonas con 50 000 lecturas).

## Dónde la estructura **no** gana: el top-K

`PriorityMinHeap` pierde frente a `ORDER BY ... LIMIT 10` en cuanto hay más de unos cientos de nodos
(0,5x con 10 000 lecturas; 0,1x con 50 000). Motivos:

1. El montículo se construye en cada llamada (`heapify` O(n)) en Python puro, y SQLite hace la selección de los K
   mejores en C, sin materializar los objetos.
2. En `/dashboard/top-risk/` los datos hay que traerlos de la base de todos modos (riesgo actual y probabilidad de
   cada nodo), así que no se ahorra ninguna consulta.

El montículo sí tiene sentido cuando los datos **ya están en memoria y se actualizan de forma incremental** (por
ejemplo, mantener el top-K al ingerir cada lectura, O(log n) por lectura) o cuando no hay una columna por la que
la base pueda ordenar. Con los datos y el volumen actuales, una consulta `ORDER BY` sería igual o mejor; se
conserva el montículo porque el ordenamiento de alertas por urgencia (clave compuesta) y la mezcla de series de
varios nodos sí se benefician (O(N log k) sin reordenar todo) y como pieza de la materia.

## Lo que la estructura cuesta

La ventaja de la tabla es real pero no es gratis:

- **Memoria** en cada worker (acotada: capacidades fijas por configuración).
- **Datos que pueden quedar viejos:** cada worker tiene su copia; se invalidan por señales y por caducidad
  (ver «Estado en memoria» en el README), pero no se sincronizan entre procesos.
- **Arranque en frío:** la primera consulta de cada nodo carga de la base (sin estos números, que son el caso caliente).
- **Complejidad de código** y de pruebas (invalidación, hilos).

Por eso cada uso conserva a la base como fuente de verdad y se puede apagar por configuración
(`NODE_STATUS_CACHE_SIZE=0`, `DASHBOARD_CACHE_SECONDS=0`, `DEDUPLICATE_READINGS=False`...).

## Reproducir

```powershell
python manage.py benchmark_structures --sizes 1000,10000,50000 --repeat 100 --db-repeat 3 --markdown
```

Los tiempos absolutos dependen de la máquina; lo que debe conservarse es la forma: constante, logarítmico o lineal.
