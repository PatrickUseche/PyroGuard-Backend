# Estructuras de datos propias

Estas estructuras viven en `api/structures/` y se implementaron a mano, sin `collections.deque`, `heapq` ni
`functools.lru_cache`, para poder razonar y medir su complejidad. Cada archivo lleva el nombre de su clase y el
costo de cada operación está también en su docstring. Las pruebas están en `api/test_structures.py`.

`n` es el número de elementos guardados, `k` una capacidad fija, `w` el tamaño de una ventana, `m` el largo de una
palabra o prefijo, `V` y `E` los vértices y aristas de un grafo.

## Resumen

| Clase | Archivo | Para qué sirve | Operación principal | Espacio |
|---|---|---|---|---|
| `RecentItemsRing` | `recent_items_ring.py` | Últimas `k` lecturas de un nodo | `append` O(1) | O(k) |
| `RollingExtremesWindow` | `rolling_extremes_window.py` | Máximo y mínimo de una ventana | `push` O(1) amortizado | O(w) |
| `BidirectionalChain` | `bidirectional_chain.py` | Orden de uso con borrado en O(1) | `remove(nodo)` O(1) | O(n) |
| `LeastRecentlyUsedCache` | `least_recently_used_cache.py` | Caché con expulsión del menos usado | `get` / `put` O(1) promedio | O(k) |
| `FirstInFirstOutQueue` | `first_in_first_out_queue.py` | Cola de espera y recorrido por niveles | `enqueue` / `dequeue` O(1) | O(n) |
| `PriorityMinHeap` | `priority_min_heap.py` | Sacar siempre el de menor prioridad | `push` / `pop` O(log n) | O(n) |
| `PrefixTrie` | `prefix_trie.py` | Buscar identificadores por prefijo | `insert` / `contains` O(m) | O(caracteres) |
| `AdjacencyGraph` | `adjacency_graph.py` | Qué nodos son vecinos | `reachable_within` O(V + E) | O(V + E) |
| `DisjointSetUnion` | `disjoint_set_union.py` | Agrupar nodos conectados en zonas | `find` / `union` O(α(n)) amortizado | O(n) |
| `PrefixSums` | `prefix_sums.py` | Suma o promedio de un rango | `range_sum` O(1) | O(n) |
| `DuplicateBloomFilter` | `duplicate_bloom_filter.py` | Descartar duplicados sin guardarlos | `add` / consulta O(1) | O(m) bits |

"O(1) promedio" significa que depende de un diccionario (tabla hash), cuyo peor caso teórico es O(n) si muchas
claves colisionan.

## Detalle

### `RecentItemsRing`: buffer circular
Arreglo de tamaño fijo con un índice de cabeza: al llenarse sobrescribe el elemento más antiguo, sin desplazar
nada ni reservar memoria. `append`, `oldest`, `newest` y `buffer[i]` son O(1); recorrerlo es O(n); crearlo o
limpiarlo es O(k). `append` devuelve el elemento expulsado, o `NOTHING_EVICTED` si todavía había lugar (distinto de
haber expulsado un `None`).

### `RollingExtremesWindow`: ventana deslizante
Dos colas monótonas (máximos y mínimos). Cada valor entra y sale de cada cola una sola vez, así que `push` es O(1)
amortizado y `maximum` / `minimum` son O(1), frente a O(w) por consulta si se recorriera la ventana.

### `BidirectionalChain`: lista doblemente enlazada
Con nodos centinela en ambos extremos, evita los casos especiales de lista vacía. Las operaciones que reciben un
nodo (`remove`, `move_to_front`, `move_to_back`) no buscan, así que son O(1); en un arreglo quitar del medio es O(n).

### `LeastRecentlyUsedCache`: caché LRU
Un diccionario lleva de la clave a su nodo y una `BidirectionalChain` guarda el orden de uso. Así `get` y `put` son
O(1) promedio y la expulsión del menos usado es O(1). `peek` y `in` no cuentan como uso.

### `FirstInFirstOutQueue`: cola FIFO
Referencias al primer y al último nodo. `enqueue` y `dequeue` son O(1) en el peor caso, a diferencia de
`list.pop(0)`, que es O(n). La usa el recorrido en anchura del grafo.

### `PriorityMinHeap`: montículo binario mínimo
Lista donde los hijos de la posición `i` están en `2i + 1` y `2i + 2`. La prioridad se calcula una vez al insertar
con una función configurable; para sacar el mayor primero se devuelve el valor negado. Los empates salen por orden
de inserción. `push` y `pop` son O(log n), `peek` O(1), `from_items` construye en O(n) y `smallest(items, k)` obtiene
el top-K en O(n + k log n).

### `PrefixTrie`: árbol de prefijos
Un nivel por carácter, así que buscar un prefijo cuesta lo que mide el prefijo y no depende de cuántas palabras
haya. Ignora mayúsculas (`casefold`) pero devuelve la palabra original, ordenada alfabéticamente. `delete` poda las
ramas que quedan vacías.

### `AdjacencyGraph`: grafo no dirigido
Diccionario de conjuntos. Añadir, consultar y quitar aristas es O(1) esperado. `reachable_within(inicio, saltos)` es
un BFS con la cola FIFO que devuelve `{vértice: saltos mínimos}` en orden de cercanía, visita cada vértice una vez
(los ciclos no provocan bucles) y cuesta O(V + E).

### `DisjointSetUnion`: Union-Find
Árboles con unión por rango y compresión de caminos: `find`, `union` y `connected` cuestan O(α(n)) amortizado, donde
α es la inversa de Ackermann (menor que 5 para cualquier `n` práctico). `groups()` devuelve los conjuntos.

### `PrefixSums`: sumas de prefijos
`totals[i]` guarda la suma de los primeros `i` valores, así que la suma de `[start, stop)` es una resta: O(1), igual
que el promedio. Se puede seguir agregando al final con `append` (O(1)). Con `float` la resta acumula error de
redondeo.

### `DuplicateBloomFilter`: filtro de Bloom
Arreglo de `m` bits y `k` posiciones por elemento (doble dispersión sobre un hash BLAKE2b). Dimensionado con
`m = ceil(-n ln p / (ln 2)^2)` y `k = round(m / n · ln 2)`. Un «no» es seguro (no hay falsos negativos); un «sí» es
solo probable, con una tasa de falsos positivos cercana a `p` mientras no se pase de los `n` elementos esperados, así
que debe confirmarse en la base de datos. No admite borrado.

## Seguridad entre hilos y workers
Ninguna estructura es segura si varios hilos la modifican a la vez: quien comparta una instancia entre peticiones
debe protegerla con un `threading.Lock`. Además, cada proceso del servidor tiene su propia copia, así que con varios
workers de gunicorn las instancias no se comparten ni se sincronizan (por eso las cachés pueden quedar desfasadas y
el filtro de Bloom solo evita trabajo, nunca decide por sí solo).

## Dónde se usarán
Ya están implementadas y probadas; su uso en la API está planificado en `TASKS.md` (Fase 3). Esta tabla se actualiza
a medida que cada task se completa.

| Estructura | Uso previsto | Task |
|---|---|---|
| `RecentItemsRing` | Últimas N lecturas por nodo y `GET /nodes/{id}/recent/` | 3.1, 3.2 |
| `RollingExtremesWindow` | Máximo y mínimo de temperatura en `/nodes/{id}/status/` | 3.4, 3.5 |
| `LeastRecentlyUsedCache` | Caché de `get_node_status` y del resumen del dashboard | 3.7, 3.8 |
| `DuplicateBloomFilter` | Descartar lecturas duplicadas en la ingesta | 3.10 |
| `PrefixTrie` | `GET /nodes/search/?prefix=` | 3.12 |
| `PriorityMinHeap` | Alertas por severidad y `GET /dashboard/top-risk/` | 3.14, 3.15 |
| `AdjacencyGraph` + `FirstInFirstOutQueue` | Vecinos y aviso a K saltos de un nodo en `FIRE` | 3.18, 3.20, 3.21 |
| `DisjointSetUnion` | Zonas de riesgo en `GET /dashboard/zones/` | 3.22, 3.23 |
| `PrefixSums` | Promedios de rango sobre series de lecturas (Fase 4) | — |
