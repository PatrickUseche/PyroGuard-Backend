# TASKS — PyroGuard Backend (Django)

Plan de mejoras del backend. Cada task es un commit; el mensaje del commit es el texto de la task con su sufijo `[x.y]`.
Al terminarla se marca `[x]` en ese mismo commit.

Este repo es parte de un sistema de tres: **PyroGuard-Backend** (este), **PyroGuard-IA** (servicio de inferencia) y
**PyroGuard-Frontend** (dashboard). Cada repo tiene su propio `TASKS.md`; las dependencias entre ellos se indican en la task.

Estado de partida (2026-10-25): ingesta con `X-API-Key`, reglas de riesgo, integración con la IA con degradación segura,
alertas con transiciones, estado de nodos, resumen de dashboard, simulador, CI y 88 pruebas en verde.

## Cómo se trabaja

- **Materia: Estructuras de datos.** Las estructuras de la Fase 2 se implementan a mano en `api/structures/` (sin apoyarse en
  `collections.deque`, `heapq` ni `functools.lru_cache` para lo que se quiere demostrar), con su complejidad documentada, y
  después se usan en una funcionalidad real del backend (Fase 3 y siguientes). Cada estructura tiene sus pruebas propias.
- **Meta de commits: más de 150 en este repo.** Cada task es un cambio lógico pequeño y real; el código, las pruebas y la
  documentación van en commits separados. Un PR por grupo de tasks, siempre desde `main` actualizado.
- Los PR no se apilan: se espera el merge del anterior si tocan los mismos archivos (`api/tests.py`, README, `TASKS.md`).

## Fase 1 — Seguridad y robustez

- [x] feat(api): límite de peticiones (throttling de DRF) distinto para las consultas GET públicas y para la ingesta [1.1] (contadores por proceso; en Render falta definir `NUM_PROXIES`)
- [x] refactor(api): decidir y documentar qué endpoints GET siguen siendo públicos y cuáles exigen autenticación [1.2] (siguen públicos por defecto; `PUBLIC_READ_ACCESS=False` los cierra cuando el frontend tenga login)
- [x] feat(api): módulo de paginación con `limit` y `offset` validados [1.3]
- [x] refactor(readings): que `filter_readings` devuelva el queryset sin recortar y la paginación lo recorte [1.4]
- [x] feat(api): paginar `/readings/` y `/nodes/{id}/readings/` con la cabecera `X-Total-Count` [1.5]
- [x] feat(alerts): paginar `/alerts/` con un límite por defecto de 100 [1.6]
- [x] feat(config): exponer `X-Total-Count` y `Retry-After` en CORS [1.7]
- [x] test(api): pruebas de offset, total y límites inválidos de la paginación [1.8]
- [x] docs(api): documentar `offset` y `X-Total-Count` en el README [1.9]
- [x] feat(auth): límite de intentos en `/auth/login/` (ámbito de throttling propio) [1.10]
- [x] test(auth): pruebas del límite de intentos de login [1.11]
- [x] feat(throttling): identificar al cliente por una cabecera de confianza configurable (`CLIENT_IP_HEADER`, p. ej. `CF-Connecting-IP` en Render) en lugar de contar saltos de proxy [1.12]
- [x] test(throttling): pruebas de la cabecera de IP (cupos por cliente, cabecera falseada o inválida y ajuste vacío) [1.13]
- [x] docs(throttling): documentar `CLIENT_IP_HEADER` y cuándo usarlo en lugar de `NUM_PROXIES` [1.14]

## Fase 2 — Estructuras de datos propias (`api/structures/`)

Cada estructura: implementación → pruebas. La complejidad de cada operación va en el docstring y en [2.24].

- [x] feat(structures): paquete `api/structures` con las convenciones y la forma de documentar complejidades [2.1]
- [x] feat(structures): buffer circular (`RingBuffer`) de capacidad fija con sobrescritura del más antiguo [2.2]
- [x] test(structures): pruebas del buffer circular (vacío, lleno, sobrescritura, iteración en orden) [2.3]
- [x] feat(structures): ventana deslizante con cola monótona para máximo y mínimo en O(1) amortizado [2.4]
- [x] test(structures): pruebas de la ventana deslizante contra una solución de fuerza bruta [2.5]
- [x] feat(structures): lista doblemente enlazada con inserción y borrado en O(1) por nodo [2.6]
- [x] test(structures): pruebas de la lista doblemente enlazada [2.7]
- [x] feat(structures): caché LRU con diccionario y lista doblemente enlazada [2.8]
- [x] test(structures): pruebas del LRU (expulsión, orden de uso, capacidad 1) [2.9]
- [x] feat(structures): cola FIFO con nodos enlazados [2.10]
- [ ] test(structures): pruebas de la cola FIFO [2.11]
- [ ] feat(structures): montículo binario mínimo con función de prioridad configurable [2.12]
- [ ] test(structures): pruebas del montículo (orden, empates, vaciado, top-K) [2.13]
- [ ] feat(structures): trie para búsqueda por prefijo [2.14]
- [ ] test(structures): pruebas del trie (prefijos, borrado, mayúsculas) [2.15]
- [ ] feat(structures): grafo con lista de adyacencia y recorrido en anchura (BFS) por saltos [2.16]
- [ ] test(structures): pruebas del grafo y del BFS (ciclos, nodos aislados, límite de saltos) [2.17]
- [ ] feat(structures): conjunto disjunto (Union-Find) con compresión de caminos y unión por rango [2.18]
- [ ] test(structures): pruebas del Union-Find [2.19]
- [ ] feat(structures): sumas de prefijos para promedios de rango en O(1) [2.20]
- [ ] test(structures): pruebas de las sumas de prefijos [2.21]
- [ ] feat(structures): filtro de Bloom para detectar duplicados [2.22]
- [ ] test(structures): pruebas del filtro de Bloom (sin falsos negativos y tasa de falsos positivos acotada) [2.23]
- [ ] docs: `docs/ESTRUCTURAS_DE_DATOS.md` con cada estructura, sus complejidades y dónde se usa [2.24]

## Fase 3 — Las estructuras en el backend

- [ ] feat(readings): buffer circular por nodo con las últimas N lecturas [3.1]
- [ ] feat(api): `GET /nodes/{id}/recent/` que sirve ese buffer sin consultar la base [3.2]
- [ ] test(api): pruebas del buffer de lecturas recientes y de `/recent/` [3.3]
- [ ] feat(readings): ventana deslizante de temperatura máxima y mínima por nodo [3.4]
- [ ] feat(nodes): exponer el máximo y el mínimo de la ventana en `/nodes/{id}/status/` [3.5]
- [ ] test(nodes): pruebas de la ventana en el estado del nodo [3.6]
- [ ] feat(cache): LRU para `get_node_status`, con invalidación al ingerir una lectura [3.7]
- [ ] feat(cache): LRU para el resumen del dashboard con caducidad corta [3.8]
- [ ] test(cache): pruebas de invalidación y de capacidad de las cachés [3.9]
- [ ] feat(ingestion): filtro de Bloom y confirmación en base para descartar lecturas duplicadas [3.10]
- [ ] test(ingestion): pruebas de lecturas duplicadas (mismo nodo y timestamp) [3.11]
- [ ] feat(api): `GET /nodes/search/?prefix=` con un trie de los `node_id` [3.12]
- [ ] test(api): pruebas de la búsqueda por prefijo [3.13]
- [ ] feat(alerts): ordenar las alertas activas por severidad y antigüedad con el montículo [3.14]
- [ ] feat(api): `GET /dashboard/top-risk/?k=` con los K nodos de mayor riesgo usando el montículo [3.15]
- [ ] test(api): pruebas del orden de alertas y del top-K [3.16]
- [ ] feat(nodes): modelo `NodeLink` para registrar qué nodos son vecinos, con migración [3.17]
- [ ] feat(nodes): construir el grafo de nodos a partir de `NodeLink` [3.18]
- [ ] feat(api): crear y listar los vecinos de un nodo [3.19]
- [ ] feat(risk): avisar a los nodos vecinos hasta K saltos de un nodo en `FIRE` con BFS [3.20]
- [ ] feat(api): `GET /nodes/{id}/neighbors/?hops=` [3.21]
- [ ] feat(nodes): zonas de riesgo: agrupar con Union-Find los nodos conectados que están en riesgo [3.22]
- [ ] feat(api): `GET /dashboard/zones/` [3.23]
- [ ] test(nodes): pruebas del grafo de nodos, de la propagación y de las zonas [3.24]

## Fase 4 — Volumen y series

- [ ] feat(readings): comando `purge_readings` con retención configurable por variable de entorno [4.1]
- [ ] test(readings): pruebas de `purge_readings` [4.2]
- [ ] docs(readings): documentar la retención en el README [4.3]
- [ ] feat(readings): modelo `ReadingHourly` con los agregados por hora, con migración [4.4]
- [ ] feat(readings): comando `aggregate_readings` que rellena los agregados [4.5]
- [ ] test(readings): pruebas de los agregados por hora [4.6]
- [ ] feat(readings): promedios de rango sobre la serie con sumas de prefijos [4.7]
- [ ] feat(api): `GET /readings/series/` que localiza el rango con búsqueda binaria [4.8] (lo consume el frontend [2.5])
- [ ] feat(api): combinar las series de varios nodos con una mezcla de K listas ordenadas (montículo) [4.9]
- [ ] test(api): pruebas de la serie, del rango y de la mezcla de nodos [4.10]
- [ ] docs(api): documentar `/readings/series/` en el README [4.11]
- [ ] test(ingestion): medir la latencia de la ingesta con la IA lenta o caída [4.12]
- [ ] feat(ingestion): cola FIFO de lecturas pendientes de evaluación por la IA, si [4.12] lo justifica [4.13]
- [ ] feat(ingestion): comando que drena la cola de evaluación [4.14]
- [ ] test(ingestion): pruebas de la cola de evaluación [4.15]

## Fase 5 — Notificaciones

- [ ] feat(alerts): interfaz `Notifier` y canal de consola [5.1]
- [ ] feat(alerts): canal de correo configurable por variables de entorno [5.2]
- [ ] feat(alerts): canal de Telegram configurable por variables de entorno [5.3]
- [ ] feat(alerts): cola de prioridad (montículo) con los avisos pendientes [5.4]
- [ ] feat(alerts): comando `send_notifications` que drena la cola por prioridad [5.5]
- [ ] feat(alerts): avisar al crear una alerta `FIRE` [5.6]
- [ ] feat(alerts): ventana deslizante para no repetir avisos del mismo nodo [5.7]
- [ ] feat(nodes): comando `check_offline_nodes` [5.8]
- [ ] feat(alerts): avisar cuando un nodo OFFLINE tiene una alerta activa [5.9]
- [ ] test(alerts): pruebas de los canales con envío simulado [5.10]
- [ ] test(alerts): pruebas de la prioridad y de la ventana de avisos [5.11]
- [ ] docs(alerts): documentar la configuración de las notificaciones [5.12]

## Fase 6 — Observabilidad y documentación

- [ ] feat(logging): formateador de logs en JSON [6.1]
- [ ] feat(logging): middleware que añade un `request_id` a cada petición y a sus logs [6.2]
- [ ] test(logging): pruebas del formato JSON y del `request_id` [6.3]
- [ ] feat(api): `GET /health/` con el estado de la base de datos [6.4] (lo usa el frontend [2.6])
- [ ] feat(api): estado de la IA dentro de `/health/` [6.5]
- [ ] test(api): pruebas de `/health/` con la base y la IA caídas [6.6]
- [ ] chore(deps): añadir drf-spectacular [6.7]
- [ ] docs(api): esquema OpenAPI y `GET /api/schema/` [6.8]
- [ ] docs(api): descripciones y ejemplos de los serializers en el esquema [6.9]
- [ ] docs: README de arquitectura con el flujo sensor → backend → IA → alertas [6.10]
- [ ] docs: actualizar la tabla de endpoints del README [6.11]

## Fase 7 — Calidad y entorno

- [ ] chore(lint): configurar ruff [7.1]
- [ ] style: corregir los avisos de ruff [7.2]
- [ ] chore(ci): paso de ruff en GitHub Actions [7.3]
- [ ] chore(ci): medir la cobertura de pruebas con coverage.py [7.4]
- [ ] chore(ci): mostrar el resumen de cobertura en el job [7.5]
- [ ] feat(admin): filtros y búsqueda de nodos [7.6]
- [ ] feat(admin): filtros y búsqueda de lecturas [7.7]
- [ ] feat(admin): filtros y búsqueda de alertas [7.8]
- [ ] feat(commands): `seed_demo` con nodos, vecinos y lecturas de ejemplo [7.9]
- [ ] test(commands): pruebas de `seed_demo` [7.10]
- [ ] feat(simulator): varios nodos a la vez con `--nodes` [7.11]
- [ ] feat(simulator): semilla reproducible con `--seed` [7.12]
- [ ] test(simulator): pruebas del simulador (hoy no tiene ninguna) [7.13]
- [ ] chore(docker): Dockerfile del backend [7.14]
- [ ] chore(docker): `docker-compose` local con el backend y la IA [7.15]
- [ ] docs: instrucciones para correr todo con Docker [7.16]
- [ ] chore(security): ajustes `SECURE_*` y cookies para producción [7.17]
- [ ] test(config): pruebas de los ajustes de producción [7.18]
- [ ] feat(commands): `benchmark_structures` que mide cada estructura frente a la consulta equivalente en base de datos [7.19]
- [ ] docs: informe de las mediciones de [7.19] y de la complejidad observada [7.20]
- [ ] chore(git): unificar los remotos del repo y limpiar las ramas ya fusionadas [7.21]

## Fase 8 — Despliegue

- [ ] docs(deploy): documentar `AI_SERVICE_URL`, `AI_API_KEY` y los timeouts en Render [8.1] (necesita la IA desplegada, ver IA [3.4])
- [x] chore(deploy): ejecutar las migraciones en un paso de release explícito [8.2] (en el build command de Render y en el `Procfile`; Render obedece el panel, no el `Procfile`)
- [x] docs(deploy): definir `NUM_PROXIES` y el límite de peticiones en Render [8.3] (se usa `CLIENT_IP_HEADER=CF-Connecting-IP`)
- [ ] docs(deploy): lista de comprobación previa al despliegue [8.4]
- [x] test(deploy): el `Procfile` migra y recopila estáticos antes de arrancar gunicorn [8.7]
- [x] fix(config): tratar una variable booleana vacía como no definida; el build de Render fallaba con `DEBUG` vacía [8.5]
- [x] test(config): pruebas de `_env_bool` (vacía, valores válidos e inválidos) [8.6]
