# TASKS — PyroGuard Backend (Django)

Plan de mejoras del backend. Cada task es un commit; el mensaje del commit es el texto de la task con su sufijo `[x.y]`.
Al terminarla se marca `[x]` en ese mismo commit.

Este repo es parte de un sistema de tres: **PyroGuard-Backend** (este), **PyroGuard-IA** (servicio de inferencia) y
**PyroGuard-Frontend** (dashboard). Cada repo tiene su propio `TASKS.md`; las dependencias entre ellos se indican en la task.

Estado de partida (2026-10-25): ingesta con `X-API-Key`, reglas de riesgo, integración con la IA con degradación segura,
alertas con transiciones, estado de nodos, resumen de dashboard, simulador, CI y 88 pruebas en verde.

## Fase 1 — Seguridad y robustez

- [x] feat(api): límite de peticiones (throttling de DRF) distinto para las consultas GET públicas y para la ingesta [1.1] (contadores por proceso; en Render falta definir `NUM_PROXIES`)
- [ ] refactor(api): decidir y documentar qué endpoints GET siguen siendo públicos y cuáles exigen autenticación [1.2]
- [ ] feat(api): paginación real en `/readings/` y `/alerts/` (hoy son listas planas con `limit` máximo de 500) [1.3]
- [ ] test(api): pruebas del throttling, de los permisos de lectura y de la paginación [1.4]

## Fase 2 — Volumen y rendimiento

- [ ] feat(readings): comando `purge_readings` con retención configurable por variable de entorno [2.1]
- [ ] feat(readings): agregados por hora (promedio y máximo por nodo) para los históricos [2.2]
- [ ] feat(api): `GET /readings/series/` con la serie agregada para los gráficos del frontend [2.3] (lo consume el frontend [2.5])
- [ ] test(ingestion): medir la latencia de la ingesta con la IA lenta o caída y decidir si hace falta una cola [2.4]
- [ ] feat(ingestion): evaluar la IA fuera de la petición del sensor, solo si [2.4] lo justifica [2.5]

## Fase 3 — Notificaciones

- [ ] feat(alerts): canal de aviso (correo o Telegram) configurable por variables de entorno, apagado por defecto [3.1]
- [ ] feat(alerts): avisar al crear una alerta `FIRE` [3.2]
- [ ] feat(nodes): comando que detecta nodos OFFLINE con una alerta activa y avisa [3.3]
- [ ] test(alerts): pruebas de los avisos con el canal simulado [3.4]

## Fase 4 — Observabilidad y documentación

- [ ] feat(logging): logs en JSON con `request_id` [4.1]
- [ ] feat(api): `GET /health/` con el estado de la base de datos y de la IA [4.2] (lo usa el frontend [2.6])
- [ ] docs(api): esquema OpenAPI del backend (drf-spectacular) [4.3]
- [ ] docs: README de arquitectura con el flujo sensor → backend → IA → alertas [4.4]

## Fase 5 — Despliegue

- [ ] docs(deploy): documentar `AI_SERVICE_URL`, `AI_API_KEY` y los timeouts en Render [5.1] (necesita la IA desplegada, ver IA [3.4])
- [ ] chore(deploy): ejecutar las migraciones en un paso de release explícito [5.2]
- [ ] chore(git): unificar los remotos del repo y limpiar las ramas ya fusionadas [5.3]
