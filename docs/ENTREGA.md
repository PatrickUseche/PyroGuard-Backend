# Entrega de PyroGuard

Estado de los tres repositorios al cierre (2026-11-17) y cómo demostrar cada parte.

## Servicios desplegados

| Componente | URL | Estado comprobado |
| --- | --- | --- |
| Frontend (Angular, Vercel) | `https://pyro-guard-frontend.vercel.app` | Responde 200 |
| Backend (Django, Render) | `https://pyroguard-backend.onrender.com/api/` | `/api/health/` responde con la base `ok` |
| IA (FastAPI, Vercel) | `https://pyro-guard-ia.vercel.app` | `/health` responde `ok` con el modelo `pyroguard-rf-1.1.0`; `/predict` exige `X-AI-API-Key` |

### Pendiente en el panel de Render

El `/api/health/` del backend desplegado mostraba `"ai": {"status": "unavailable"}` aunque la IA responde: el backend
no llega a la URL configurada. Hay que revisar en *Environment* del servicio `pyroguard-backend`:

1. `AI_SERVICE_URL=https://pyro-guard-ia.vercel.app` (sin barra final ni `/predict`).
2. `AI_API_KEY` igual a la `AI_API_KEY` del proyecto de la IA en Vercel.
3. Volver a desplegar y comprobar con `python manage.py check_ai` (pestaña *Shell*) o con el campo `reason` de
   `/api/health/` (ver «Conectar con PyroGuard-IA» en el README).

## Tareas

| Repositorio | `TASKS.md` | Pruebas | Lint |
| --- | --- | --- | --- |
| PyroGuard-Backend | Fases 1–13 completas | 891 pruebas, 99 % de cobertura (mínimo del CI: 98 %) | ruff con E, W, F, I, B, UP, SIM, C4, RET y RUF100 |
| PyroGuard-IA | Fases 0–6 completas (5.4: desplegada en Vercel) | 264 pruebas, 92 % de cobertura | ruff con E, W, F, I, B, UP y SIM |
| PyroGuard-Frontend | Fases 0–9 completas; 4.6–4.9 se hicieron como 6.1–6.4 | 148 pruebas, `ng build`, ESLint y Prettier en verde | angular-eslint |

## Cómo demostrarlo

1. **Salud del sistema:** abrir `https://pyroguard-backend.onrender.com/api/health/` y
   `https://pyro-guard-ia.vercel.app/health`.
2. **Ingesta con el simulador:** `python simulador_iot.py --url https://pyroguard-backend.onrender.com/api/readings/
   --api-key <INGEST_API_KEY> --nodes 3 --scenario fire` y ver las alertas en el dashboard. Los nodos `SIM-001` a
   `SIM-003` deben existir antes (admin o `python manage.py seed_demo`).
3. **Dashboard:** iniciar sesión con Google en el frontend, revisar el mapa, el detalle de un nodo y reconocer una
   alerta.
4. **Estructuras de datos:** `docs/ESTRUCTURAS_DE_DATOS.md` y `python manage.py benchmark_structures`
   (resultados en `docs/BENCHMARKS.md`).
5. **Pruebas:** `python manage.py test api` en el backend, `python -m pytest -q` en la IA y `npm test` en el frontend.

## Limitaciones declaradas

- El modelo de IA se entrenó con datos sintéticos; no es un detector certificado de incendios reales.
- El estado en memoria (cachés, lecturas recientes) es por proceso: el backend corre con un solo worker.
- Las tareas programadas (`send_notifications`, `check_offline_nodes`, mantenimiento) necesitan Cron Jobs de Render,
  que son de pago; sin ellos los avisos no se envían solos (ver `TASKS.md` [11.5]).
