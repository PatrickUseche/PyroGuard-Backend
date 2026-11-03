from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        from . import cache_signals  # noqa: F401  (registra las señales)
