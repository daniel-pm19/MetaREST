"""Resolve only the headers explicitly configured for one SUT project."""

import json
import os
import re

_ENV_NAME = re.compile(r"SUT_[A-Z0-9_]+\Z")
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")


class SUTAuthError(ValueError):
    """Safe configuration error: messages never contain header values or raw JSON."""


def project_headers(auth_env_key: str | None) -> dict[str, str]:
    if auth_env_key is None:
        return {}
    if not isinstance(auth_env_key, str) or not _ENV_NAME.fullmatch(auth_env_key):
        raise SUTAuthError("auth_env_key debe indicar una variable SUT_* válida")
    raw = os.environ.get(auth_env_key)
    if raw is None or not raw.strip():
        raise SUTAuthError(f"Falta configurar la variable {auth_env_key} de este proyecto")
    try:
        headers = json.loads(raw)
    except ValueError:
        raise SUTAuthError(f"La variable {auth_env_key} debe contener un objeto JSON de headers") from None
    if not isinstance(headers, dict) or any(
        not isinstance(name, str)
        or not _HEADER_NAME.fullmatch(name)
        or not isinstance(value, str)
        or not value.isascii()
        or "\r" in value
        or "\n" in value
        for name, value in headers.items()
    ):
        raise SUTAuthError(f"La variable {auth_env_key} debe contener headers HTTP con valores de texto válidos")
    return headers
