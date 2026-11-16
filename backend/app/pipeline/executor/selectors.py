"""JSONPath selection over response bodies."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from jsonpath_ng import JSONPath
from jsonpath_ng.exceptions import JsonPathLexerError, JsonPathParserError
from jsonpath_ng.ext import parse


class SelectorError(ValueError):
    """Invalid expression, or the selected field does not exist in the response."""


@lru_cache(maxsize=512)
def compile_selector(expr: str) -> JSONPath:
    try:
        return parse(expr)
    except (JsonPathLexerError, JsonPathParserError) as exc:
        raise SelectorError(f"selector JSONPath inválido {expr!r}: {exc}") from exc
    except Exception as exc:  # jsonpath-ng also raises bare Exception for some syntax errors
        raise SelectorError(f"selector JSONPath inválido {expr!r}: {exc}") from exc


def select(body: Any, expr: str) -> list[Any]:
    """Return every value matched by ``expr``.

    An empty list is a legitimate result only when the selector iterates an
    array that exists and is empty (``$.results[*].id`` over ``{"results": []}``).
    If the field itself is missing, it is an error: the MR is pointing to
    something the API does not return.
    """
    if body is None:
        raise SelectorError("la respuesta no tiene cuerpo JSON")
    matches = [m.value for m in compile_selector(expr).find(body)]
    if matches:
        return matches
    container = _array_container(expr)
    if container is not None:
        found = [m.value for m in compile_selector(container).find(body)]
        if found and all(isinstance(v, list) for v in found):
            return []
    raise SelectorError(f"el selector {expr!r} no encontró nada en la respuesta")


def _array_container(expr: str) -> str | None:
    """'$.results[*].id' -> '$.results' (the array whose emptiness explains no matches)."""
    idx = expr.find("[*]")
    if idx <= 0:
        return None
    return expr[:idx] or None
