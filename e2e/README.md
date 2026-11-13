# Pruebas de la API con Playwright

Se ejecutan contra un backend **local** con SQLite; nunca contra producción (las pruebas escriben lecturas y alertas).

```bash
# 1. Backend de pruebas (desde la raíz del repo)
export DATABASE_URL= DEBUG=True INGEST_API_KEY=e2e-ingest-key AI_SERVICE_URL= \
       THROTTLE_READ_RATE=100000/min THROTTLE_INGEST_RATE=100000/min
python manage.py migrate
python manage.py seed_demo --reset --seed 1
python manage.py runserver 8000

# 2. Dos usuarios con token (uno en el grupo «Operadores»)
python manage.py shell -c "
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.authtoken.models import Token
U = get_user_model()
op, _ = U.objects.get_or_create(username='e2e_operator', defaults={'email': 'e2e@example.com'})
op.groups.add(Group.objects.get(name='Operadores'))
vw, _ = U.objects.get_or_create(username='e2e_viewer', defaults={'email': 'v@example.com'})
print('E2E_OPERATOR_TOKEN=' + Token.objects.get_or_create(user=op)[0].key)
print('E2E_VIEWER_TOKEN=' + Token.objects.get_or_create(user=vw)[0].key)
"

# 3. Pruebas
cd e2e && npm install && npx playwright test
```

Variables: `E2E_API_URL` (por defecto `http://localhost:8000/api/`), `E2E_INGEST_API_KEY`
(por defecto `e2e-ingest-key`), `E2E_OPERATOR_TOKEN` y `E2E_VIEWER_TOKEN`.
Cada prueba usa marcas de tiempo únicas, así que se puede repetir sin volver a sembrar;
siembra de nuevo con `--reset` si quieres un estado limpio.
