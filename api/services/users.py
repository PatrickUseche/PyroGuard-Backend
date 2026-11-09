import re
from collections.abc import Callable

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from api.models import GoogleAccount

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


def create_google_user(email, google_sub, username, given_name=None):
    user_manager = get_user_model()._default_manager
    with transaction.atomic():
        user = user_manager.create_user(
            username=username,
            email=email,
            is_staff=False,
            is_superuser=False,
        )
        user.set_unusable_password()
        update_fields = ["password"]
        if isinstance(given_name, str):
            user.first_name = given_name[:150]
            update_fields.append("first_name")
        user.save(update_fields=update_fields)
        GoogleAccount.objects.create(user=user, google_sub=google_sub)
    return user


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
