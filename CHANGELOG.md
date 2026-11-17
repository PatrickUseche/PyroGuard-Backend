# Cambios de PyroGuard-Backend

Resumen por fases; el detalle de cada cambio está en `TASKS.md` y en el historial de commits (un commit por task).

## Fase 13 — Entrega (2026-11-17)

- `/api/health/` explica con `reason` por qué la IA no está disponible y su timeout se configura con `AI_HEALTH_TIMEOUT`.
- Comando `python manage.py check_ai` para diagnosticar la conexión con PyroGuard-IA.
- URL real de la IA (`https://pyro-guard-ia.vercel.app`) y del frontend en el README y en `render.yaml`.
- ruff con más reglas (UP, SIM, C4, RET, RUF100), cobertura del 99 % y mínimo del CI en 98 %.
- `docs/ENTREGA.md` con el estado de los tres repositorios.

## Fases 11–12 — Persistencia y pruebas E2E (2026-11-12)

- Restricción única `(node, timestamp)`, reparación de lecturas sin evaluación y 404 en español y en JSON.
- Pruebas de la API con Playwright.

## Fases 9–10 — Acceso y registro con Google

- `POST /api/auth/google/`, registro con nombre de usuario propio, `GET /api/auth/me/` y cierre de sesión.
- Grupo «Operadores» con permiso para reconocer y cerrar alertas.

## Fases 6–8 — Observabilidad, calidad y despliegue

- Logs en JSON con `request_id`, `GET /api/health/`, esquema OpenAPI, ruff y cobertura en el CI.
- Dockerfile, `docker-compose`, ajustes de producción y Blueprint de Render.

## Fases 2–5 — Estructuras de datos, series y notificaciones

- Estructuras propias en `api/structures/` usadas en lecturas recientes, cachés LRU, duplicados, búsqueda por
  prefijo, top-K, grafo de vecinos y zonas de riesgo.
- Series por rango, agregados por hora, cola de evaluación diferida y avisos por consola, correo y Telegram.

## Fase 1 — Seguridad y robustez

- Límite de peticiones, paginación con `X-Total-Count` y cabecera de IP de confianza.
