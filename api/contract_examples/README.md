# Ejemplos del contrato IA-Backend v1.0

Ejemplos ejecutables de `docs/CONTRATO_IA_BACKEND.md`. Ambos repositorios los usan en sus pruebas:

| Repositorio | Ubicación | Qué verifica |
|---|---|---|
| PyroGuard-IA | `docs/contract/examples/` | La API acepta las peticiones y produce exactamente estas respuestas |
| PyroGuard-Backend | `api/contract_examples/` | El backend genera peticiones válidas e interpreta estas respuestas |

Las dos carpetas deben tener **el mismo contenido**. Al cambiar el contrato:

1. Actualiza los ejemplos aquí y ejecuta `python -m pytest -q`.
2. Si cambió `response_ok.json`, regenéralo desde la API (no lo edites a mano).
3. Copia la carpeta completa a `PyroGuard-Backend/api/contract_examples/` y ejecuta `python manage.py test`.

| Archivo | Contenido |
|---|---|
| `request_fire.json` | Lectura de incendio con todos los campos |
| `request_backend_limits.json` | Valores límite que el backend acepta (`gas: null`, 150 °C, humo alto) |
| `response_ok.json` | Respuesta real de `/predict` para `request_fire.json` |
| `error_validation.json` | 422 `VALIDATION_ERROR` |
| `error_unauthorized.json` | 401 `UNAUTHORIZED` |
| `error_model_unavailable.json` | 503 `MODEL_UNAVAILABLE` |
