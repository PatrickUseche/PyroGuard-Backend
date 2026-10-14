import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback


logger = logging.getLogger(__name__)


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

    response.data = {
        "status": "error",
        "errors": response.data,
    }
    return response
