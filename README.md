# PyroGuard Backend

## Ingesta de lecturas

`POST /api/readings/` requiere autenticación. Los sensores y el simulador deben
enviar la clave configurada en `INGEST_API_KEY` mediante el header HTTP
`X-API-Key`. La clave no forma parte del JSON de la lectura. Si no se configura
la variable, la ingesta por API key queda rechazada.

El payload de lecturas conserva el contrato vigente. `GET /api/readings/` es
público y devuelve las últimas lecturas como una lista JSON plana.

Para ejecutar el simulador, define `INGEST_API_KEY` como variable de entorno
antes de iniciar `simulador_iot.py`.

## Migraciones y despliegue

Antes de servir tráfico que utilice autenticación por token, instala los
requisitos y revisa las migraciones pendientes:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate --plan
```

Revisa el plan y después aplica las migraciones:

```powershell
python manage.py migrate
```

Este comando también crea las tablas de `rest_framework.authtoken` declaradas
por Django REST Framework. En Render, ejecútalo explícitamente en el servicio
backend y contra su entorno/base de datos correspondiente antes de dirigir
tráfico a la versión que dependa de esas tablas. El `Procfile` no aplica
migraciones automáticamente. No ejecutes el comando contra producción sin
revisar antes `migrate --plan` y confirmar la base de datos seleccionada.
