import logging

from django.http import Http404, JsonResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

logger = logging.getLogger(__name__)

NOT_FOUND_MESSAGE = "No se encontró el recurso solicitado."


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        set_rollback()
        logger.error(
            "Excepción inesperada en la API. Tipo: %s",
            type(exc).__name__,
        )
        return Response(
            {
                "status": "error",
                "errors": {"detail": "Error interno del servidor."},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, Http404):
        # El mensaje de get_object_or_404 sale en inglés ("No Node matches the given query.").
        response.data = {"detail": NOT_FOUND_MESSAGE}

    response.data = {
        "status": "error",
        "errors": response.data,
    }
    return response


def api_not_found(request, *args, **kwargs):
    """404 en JSON para las rutas de ``/api/`` que no existen (en vez de la página HTML de Django)."""
    return JsonResponse(
        {"status": "error", "errors": {"detail": NOT_FOUND_MESSAGE}},
        status=status.HTTP_404_NOT_FOUND,
    )
