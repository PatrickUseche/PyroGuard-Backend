import re
from collections.abc import Callable

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

_RESERVED_USERNAMES = {"admin", "root", "administrator", "pyroguard", "soporte"}
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{4,16}$")


def validate_username(value: str) -> None:
    if len(value) < 4 or len(value) > 16:
        raise ValidationError("El nombre de usuario debe tener entre 4 y 16 caracteres.")
    if _USERNAME_PATTERN.fullmatch(value) is None:
        raise ValidationError(
            "Usa solo letras, números, guion, guion bajo o punto."
        )
    if value.lower() in _RESERVED_USERNAMES or get_user_model()._default_manager.filter(
        username__iexact=value
    ).exists():
        raise ValidationError("Ese nombre de usuario no está disponible.")


def build_username(email: str, exists: Callable[[str], bool]) -> str:
    local_part = email.partition("@")[0].lower()
    base = re.sub(r"[^a-z0-9_.-]", "", local_part)[:16]
    if len(base) < 4:
        base = (base + "usuario")[:16]

    username = base
    suffix = 1
    while username in _RESERVED_USERNAMES or exists(username):
        suffix_text = str(suffix)
        prefix_length = max(0, 16 - len(suffix_text))
        username = f"{base[:prefix_length]}{suffix_text}"
        suffix += 1

    return username
