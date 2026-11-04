import re
from collections.abc import Callable


_RESERVED_USERNAMES = {"admin", "root", "administrator", "pyroguard", "soporte"}


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
