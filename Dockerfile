# Imagen del backend de PyroGuard (Django + gunicorn).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Primero las dependencias: así Docker reutiliza esta capa mientras requirements.txt no cambie.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# El proceso no corre como root.
RUN useradd --system --create-home --uid 10001 pyroguard && chown -R pyroguard /app
USER pyroguard

EXPOSE 8000

# Mismo arranque que el Procfile de Render: migrar, recopilar estáticos y servir.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
