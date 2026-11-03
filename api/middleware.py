import re
import uuid

from django.core.signals import request_finished
from django.dispatch import receiver

from .logging_utils import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIdMiddleware:
    """Da un identificador a cada petición y lo pone en sus logs y en la respuesta.

    Si el cliente o el proxy ya mandan ``X-Request-ID`` con un valor razonable se reutiliza
    (así se puede seguir una petición de punta a punta); si no, se genera uno. Un valor con
    caracteres raros o demasiado largo se descarta para que nadie pueda inyectar líneas en los logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = supplied if _VALID_ID.fullmatch(supplied) else uuid.uuid4().hex
        request.request_id = request_id
        # No se restablece aquí: Django registra las respuestas 4xx/5xx (``django.request``)
        # después de que la cadena de middleware termina, y deben llevar el mismo id.
        request_id_var.set(request_id)
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request_id
        return response


@receiver(request_finished)
def clear_request_id(sender, **kwargs):
    """Al cerrar la respuesta, el hilo deja de pertenecer a esa petición."""
    request_id_var.set("-")
