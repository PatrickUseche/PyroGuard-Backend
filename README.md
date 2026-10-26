# PyroGuard Backend

API Django REST Framework para recibir lecturas IoT, clasificarlas con reglas,
mantener alertas persistentes y exponer el estado de nodos para el dashboard.
El riesgo se evalúa con reglas deterministas y, si `AI_SERVICE_URL` está
configurada, con la probabilidad del servicio PyroGuard-IA, que solo puede
elevar el nivel. Si la IA no responde, la lectura se guarda y se evalúa solo
con reglas.

## Arquitectura

- `api/models.py`: nodos, lecturas, evaluaciones de riesgo y alertas.
- `api/services/`: reglas de riesgo, ingesta, consultas, nodos y alertas.
- `api/serializers.py`, `api/views.py` y `api/urls.py`: contratos y endpoints.
- `config/settings.py`: configuración por variables de entorno, DRF, CORS,
	WhiteNoise y base de datos.
- `simulador_iot.py`: productor de lecturas con escenarios controlados.

## Requisitos

- Python 3.13 o compatible con Django 6.1.
- SQLite para desarrollo; PostgreSQL recomendado para despliegue.
- Dependencias fijadas en `requirements.txt`.

## Ejecución local

En PowerShell, desde la raíz del backend:

```powershell
python -m venv .venv
\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` para desarrollo local. `DEBUG=True` y `DATABASE_URL=` seleccionan
SQLite. Aplica las migraciones y crea un usuario administrador:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

El panel de administración queda en `http://localhost:8000/admin/`.

## Variables de entorno

| Variable | Uso | Valor local de ejemplo |
| --- | --- | --- |
| `SECRET_KEY` | Secreto Django; obligatorio con `DEBUG=False` | Vacío en desarrollo, Django genera uno temporal |
| `DEBUG` | Activa modo de desarrollo | `True` |
| `DATABASE_URL` | URL PostgreSQL; vacía usa SQLite | Vacía |
| `INGEST_API_KEY` | Clave del header `X-API-Key` para ingesta | Definir una clave local propia |
| `NODE_OFFLINE_THRESHOLD_SECONDS` | Segundos sin comunicación para marcar OFFLINE | `300` |
| `ALERT_ON_WARNING` | Habilita alertas WARNING | `False` |
| `AUTO_REGISTER_NODES` | Crea nodos desconocidos durante la ingesta | `False` |
| `AI_SERVICE_URL` | URL base de PyroGuard-IA; vacía deshabilita la IA | `http://127.0.0.1:8001` |
| `AI_CONNECT_TIMEOUT` | Segundos máximos para conectar con la IA (> 0) | `3.0` |
| `AI_READ_TIMEOUT` | Segundos máximos de espera de la inferencia (> 0) | `10.0` |
| `AI_API_KEY` | Clave enviada en `X-AI-API-Key`; igual a la del servicio IA | Vacía en local |
| `LOG_LEVEL` | Nivel de logging | `INFO` |
| `PUBLIC_READ_ACCESS` | Si es `False`, las consultas GET también exigen token | `True` |
| `THROTTLE_READ_RATE` | Límite de consultas GET por IP (`N/sec`, `N/min`, `N/hour` o `N/day`) | `120/min` |
| `THROTTLE_INGEST_RATE` | Límite de ingesta POST de lecturas por IP, con el mismo formato | `300/min` |
| `NUM_PROXIES` | Saltos de proxy delante de la app, para identificar la IP del cliente | Vacío |
| `EXTRA_ALLOWED_HOSTS` | Hosts adicionales separados por comas | Vacío |
| `EXTRA_CORS_ORIGINS` | Orígenes CORS adicionales separados por comas | Vacío |

No publiques `.env`, claves API, tokens ni `SECRET_KEY`. `.env` está excluido
por `.gitignore`; `.env.example` contiene nombres de variables y placeholders.

## Endpoints

La base común es `http://localhost:8000/api`. Las consultas GET son públicas por
defecto (ver «Acceso de lectura»). Las escrituras de nodos y transiciones de
alertas requieren autenticación DRF.
La ingesta POST requiere `X-API-Key`, incluso si el cliente también tiene sesión
o token; con `DEBUG=True` y `INGEST_API_KEY` vacía se permite para desarrollo y
se registra una advertencia.

| Método y ruta | Descripción |
| --- | --- |
| `GET /readings/` | Lista plana; filtros `node_id`, `from`, `to`, `range`, `limit`, `offset`, `order` |
| `POST /readings/` | Ingresa una lectura, persiste riesgo y puede crear/actualizar alerta |
| `GET /nodes/`, `POST /nodes/` | Listar nodos / crear nodo autenticado |
| `GET`, `PUT`, `PATCH`, `DELETE /nodes/{node_id}/` | CRUD de un nodo; `node_id` no cambia |
| `GET /nodes/{node_id}/status/` | Estado, última lectura, riesgo y alertas activas |
| `GET /nodes/{node_id}/readings/` | Lecturas del nodo con los mismos filtros de `/readings/` |
| `GET /dashboard/summary/` | Conteos, riesgo global y última lectura por nodo |
| `GET /alerts/`, `GET /alerts/active/`, `GET /alerts/{id}/` | Consultar alertas e historial; `/alerts/` acepta `limit` (por defecto 100) y `offset` |
| `POST /alerts/{id}/acknowledge/`, `POST /alerts/{id}/close/` | Cambiar estado con autenticación |
| `POST /auth/login/` | Obtener token de DRF |

Autenticación de ingesta:

```bash
curl -X POST http://localhost:8000/api/readings/ \
	-H "Content-Type: application/json" \
	-H "X-API-Key: $INGEST_API_KEY" \
	-d '{"node_id":"SIM-001","temperature":24.5,"humidity":48,"smoke":18,"gas":3.2,"flame":false,"timestamp":"2026-10-17T15:30:00Z"}'
```

Token para operaciones autenticadas:

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
	-H "Content-Type: application/json" \
	-d '{"username":"USUARIO","password":"CONTRASENA"}'

curl -H "Authorization: Token TOKEN_RECIBIDO" \
	http://localhost:8000/api/nodes/
```

Ejemplo de status y filtros de lectura:

```bash
curl http://localhost:8000/api/nodes/SIM-001/status/
curl "http://localhost:8000/api/readings/?node_id=SIM-001&range=24h&limit=50&order=desc"
curl http://localhost:8000/api/dashboard/summary/
```

## Acceso de lectura

| Endpoint | Lectura (GET) | Escritura |
| --- | --- | --- |
| `/readings/`, `/dashboard/summary/`, `/nodes/…`, `/alerts/…` | Pública | Nodos y transiciones de alertas: token. Lecturas: `X-API-Key` |
| `/auth/login/` | — | Siempre abierto, para poder obtener el token |

Hoy son públicas porque el dashboard aún no tiene inicio de sesión. Con
`PUBLIC_READ_ACCESS=False` todas las consultas GET responden HTTP 401 sin
`Authorization: Token …`, sin tocar código. La ingesta con `X-API-Key` y el login
no cambian. Las lecturas muestran estado de nodos y alertas, por lo que conviene
cerrarlas en cuanto el frontend pueda enviar el token.

## Límite de peticiones

Cada IP tiene dos cupos independientes: las consultas GET (`THROTTLE_READ_RATE`,
compartido por todos los endpoints de lectura) y la ingesta POST de lecturas
(`THROTTLE_INGEST_RATE`, holgado para varios nodos detrás de una misma red). Al
superarlos la API responde HTTP 429 con la cabecera `Retry-After`. Las
peticiones sin credenciales válidas se rechazan antes de contar contra el cupo
de ingesta.

Los contadores viven en la memoria de cada proceso, así que con varios workers
de gunicorn el límite efectivo se multiplica por el número de workers. Detrás
de un proxy (Render), define `NUM_PROXIES` con el número de saltos para que se
cuente la IP real del cliente; sin valor se usa todo `X-Forwarded-For`, que un
cliente puede falsear para esquivar el límite.

## Contrato de lectura

Los campos obligatorios son `node_id`, `temperature`, `humidity`, `smoke`,
`flame` y `timestamp`. `gas` es opcional y acepta `null`. `flame` acepta
booleano o `0`/`1`. Timestamp debe ser ISO 8601 y no puede superar cinco
minutos en el futuro. Rangos aceptados: temperatura `-50..150`, humedad
`0..100`, humo `>=0` y gas `>=0`.

```json
{
	"node_id": "SIM-001",
	"temperature": 24.5,
	"humidity": 48,
	"smoke": 18,
	"gas": 3.2,
	"flame": false,
	"timestamp": "2026-10-17T15:30:00Z"
}
```

`GET /api/readings/` devuelve siempre una lista JSON plana, incluso sin
resultados (`[]`). `range` acepta `24h` o `7d`; `limit` va de 1 a 500 y por
defecto es 20; `order` acepta `asc` o `desc` y por defecto es `desc`.

Paginación: `offset` (0 por defecto) salta esa cantidad de resultados tras
aplicar filtros y orden. La respuesta sigue siendo una lista plana y la
cabecera `X-Total-Count` trae el total de resultados del filtro, sin contar
`limit` ni `offset`, para que el cliente calcule las páginas. También rigen en
`/nodes/{node_id}/readings/` y en `/alerts/` (donde `limit` vale 100 por
defecto). La cabecera se expone por CORS. Un `limit` fuera de 1–500 o un
`offset` negativo o no numérico devuelven HTTP 400.

```bash
curl -i "http://localhost:8000/api/readings/?node_id=SIM-001&limit=20&offset=40"
```

Cada lectura incluye `risk_level`, la decisión final del backend, y `ai`, el
resultado de PyroGuard-IA usado como evidencia (`null` si la lectura aún no
tiene evaluación):

```json
"ai": {
	"status": "OK",
	"risk_level": "WARNING",
	"probability": 0.6,
	"probabilities": {"NORMAL": 0.4, "WARNING": 0.35, "FIRE": 0.25},
	"model_version": "pyroguard-rf-1.0.0"
}
```

`status` puede ser `OK`, `DISABLED` (sin `AI_SERVICE_URL`), `UNAVAILABLE`
(timeout, conexión o error del servicio), `REJECTED` (credencial o datos
rechazados) o `INVALID_RESPONSE`. Si no es `OK`, el riesgo se calcula solo con
reglas y los demás campos de `ai` son `null` o `{}`. La IA puede elevar el nivel
de riesgo, pero nunca reducir el resultado de las reglas.

## Reglas de riesgo

Los umbrales son valores del prototipo, ajustables por el equipo, definidos en
`api/services/risk_rules.py`:

| Constante | Umbral |
| --- | ---: |
| `SMOKE_WARNING` | 40 |
| `SMOKE_FIRE` | 60 |
| `TEMP_WARNING` | 40 |
| `TEMP_FIRE` | 50 |
| `HUMIDITY_DRY` | 25 |

Son señales: llama activa; humo `>=40`; temperatura `>=40`; humedad `<=25` con
temperatura `>=35`. Son señales fuertes: llama, humo `>=60` y temperatura
`>=50`. `FIRE` requiere dos señales fuertes; una llama aislada queda en
`WARNING`. Una o más señales no fuertes producen `WARNING`; sin señales es
`NORMAL`.

La interfaz para IA recibe `ai_probability` (ahora `None`): `>=0.85` junto con
alguna señal de sensor eleva a `FIRE`; `>=0.5` eleva como mínimo a `WARNING`.
La IA nunca reduce el nivel calculado por sensores. No hay servicio de predicción
implementado todavía.

## Estado y alertas

Un nodo sin comunicación conocida es `UNKNOWN`. Si el último contacto ocurrió
dentro de `NODE_OFFLINE_THRESHOLD_SECONDS`, es `ONLINE`; si excede el umbral, es
`OFFLINE`. Para nodos offline, `/status/` conserva el último riesgo conocido y
marca `current_risk_stale=true`: es historial, no un riesgo actual confirmado.
El resumen global considera solo nodos online.

Se crea alerta para `FIRE`; las de `WARNING` dependen de `ALERT_ON_WARNING`.
Una alerta del mismo nodo y nivel en `ACTIVE` o `ACKNOWLEDGED` se actualiza:
incrementa `occurrences` y cambia `last_seen_at`. Un ascenso de WARNING a FIRE
crea una alerta FIRE separada. Cerrar una alerta permite que un evento futuro
genere una nueva. Las alertas no se eliminan al reconocerlas o cerrarlas.

Transiciones válidas: `ACTIVE -> ACKNOWLEDGED -> CLOSED` y `ACTIVE -> CLOSED`.
Las transiciones inválidas devuelven HTTP 409; reconocimiento y cierre registran
sus fechas y requieren autenticación.

## Simulador

El simulador usa por defecto `API_URL` o `http://localhost:8000/api/readings/`,
`NODE-001`, cinco segundos y `INGEST_API_KEY`. Para nodos de prueba se recomienda
el prefijo `SIM-`, por ejemplo `SIM-001`.

```powershell
python simulador_iot.py --node SIM-001 --scenario normal
python simulador_iot.py --node SIM-001 --scenario warning --interval 2
python simulador_iot.py --node SIM-001 --scenario fire --api-key $env:INGEST_API_KEY
python simulador_iot.py --url http://localhost:8000/api/readings/ --scenario random
```

Escenarios `normal`, `warning` y `fire` son reproducibles por categoría; sus
mediciones varían dentro de rangos que corresponden a las reglas. `random`
elige categorías con pesos 85/10/5. El log identifica las lecturas como
`SIMULADO`. El simulador importa umbrales del paquete del backend y debe
ejecutarse desde la raíz del backend.

## Pruebas

Usa SQLite local, sin `DATABASE_URL`, y activa `DEBUG` en PowerShell:

```powershell
$env:DEBUG = "True"
$env:DATABASE_URL = ""
python manage.py check
python manage.py makemigrations --check
python manage.py test
```

El test runner crea y destruye su propia base SQLite temporal. No uses una URL
de una base compartida para estas comprobaciones. Los tests nunca llaman al
servicio de IA real: la red se simula.

`api/contract_examples/` es una copia de `docs/contract/examples/` de
PyroGuard-IA, y ambas suites la usan para verificar el contrato IA-Backend.
Si el contrato cambia, actualiza la carpeta en PyroGuard-IA y cópiala aquí sin
modificarla. GitHub Actions ejecuta estas comprobaciones en cada pull request.

## Despliegue en Render

1. Crear un servicio web desde el repositorio del backend.
2. Build command: `pip install -r requirements.txt`.
3. El `Procfile` ejecuta `collectstatic` y `gunicorn config.wsgi:application`.
4. Configurar `DEBUG=False`, `SECRET_KEY`, `DATABASE_URL`, `INGEST_API_KEY` y
	 el resto de variables necesarias en el entorno de Render. Agregar dominios
	 con `EXTRA_ALLOWED_HOSTS` y orígenes con `EXTRA_CORS_ORIGINS` cuando proceda.
5. Aplicar migraciones explícitamente contra la base de Render antes de servir
	 tráfico: `python manage.py migrate`. El Procfile no migra automáticamente.
6. Confirmar que el origen del frontend esté permitido por CORS y que el host
	 de la API esté permitido en `ALLOWED_HOSTS`.

No ejecutes migraciones de producción desde una terminal local sin confirmar
explícitamente la conexión seleccionada.
