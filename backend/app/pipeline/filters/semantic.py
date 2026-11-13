"""Semantic validity rules: is the MR supported by the OpenAPI spec?

Deterministic and cheap, so they run before the LLM check: an MR that breaks a rule
is discarded as ``invalid_semantics`` without spending tokens. Messages are in
Spanish because the QA Auditor reads them in the "Descartados" view.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.mr import (
    HttpMethod,
    Measure,
    MRNotExecutableError,
    MRSpec,
    ParamValue,
    RelationType,
    RequestSpec,
)
from app.pipeline.context_extractor import MAX_FIELDS, ApiContext, OperationContext, ParamContext

MAX_VIOLATIONS = 10

# Relations that compare collections: a selector returning one scalar makes them meaningless.
COLLECTION_RELATIONS = {
    RelationType.SUBSET,
    RelationType.DISJOINT,
    RelationType.COMPLETE,
    RelationType.DIFFERENCE,
    RelationType.SAME_ORDER,
}

_INT = re.compile(r"-?\d+")
# Index, slice or filter inside brackets -> treated as [*] when matching against response fields.
_INDEXER = re.compile(r"\[(?:-?\d+|-?\d*:-?\d*(?::-?\d+)?|\?\(.*?\))\]")


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            return value.is_integer()
        return bool(_INT.fullmatch(str(value)))
    if expected == "number":
        return _as_number(value) is not None
    if expected == "boolean":
        return isinstance(value, bool) or str(value).lower() in ("true", "false")
    return True  # string / unknown: any scalar can be sent as text


def _value_violations(p: ParamContext, value: ParamValue, where: str) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        if p.type != "array" and len(value) != 1:
            out.append(f"'{p.name}' en {where} no acepta una lista de valores")
        values = value
    else:
        values = [value]
    expected = (p.items_type or "string") if p.type == "array" else p.type
    for v in values:
        if not _type_ok(expected, v):
            out.append(f"'{p.name}' en {where} debe ser {expected}, pero recibe {_text(v)!r}")
            continue
        if p.enum and _text(v) not in {_text(e) for e in p.enum}:
            allowed = ", ".join(_text(e) for e in p.enum)
            out.append(f"'{p.name}' en {where} vale {_text(v)!r}, que no está entre los permitidos ({allowed})")
        number = _as_number(v) if expected in ("integer", "number") else None
        if number is not None and p.minimum is not None and number < p.minimum:
            out.append(f"'{p.name}' en {where} vale {_text(v)}, por debajo del mínimo {_text(p.minimum)}")
        if number is not None and p.maximum is not None and number > p.maximum:
            out.append(f"'{p.name}' en {where} vale {_text(v)}, por encima del máximo {_text(p.maximum)}")
    return out


def _request_violations(req: RequestSpec, ctx: ApiContext) -> list[str]:
    where = f"{req.method.value} {req.path}"
    if req.method is HttpMethod.HEAD:
        return [f"{where}: HEAD no devuelve cuerpo, así que la relación no se puede evaluar"]
    op = ctx.find_operation(req.method.value, req.path)
    if op is None:
        return [f"{where} no existe en la especificación"]
    out: list[str] = []
    for location, params in (("query", req.query_params), ("path", req.path_params)):
        for name, value in params.items():
            p = op.param(name, location)
            if p is None:
                out.append(f"el parámetro de {location} '{name}' no existe en {where}")
            else:
                out.extend(_value_violations(p, value, where))
    for p in op.parameters:
        if p.required and p.location == "query" and p.name not in req.query_params:
            out.append(f"falta el parámetro obligatorio '{p.name}' en {where}")
    return out


def field_type(selector: str, op: OperationContext) -> str | None:
    """Type of the response field a selector points to.

    Returns ``None`` when it cannot be known (no response schema, or the field list was
    truncated) and ``""`` when the selector matches no known field.
    """
    fields = op.response_fields
    if selector == "$":
        return "object"
    if not fields:
        return None
    normalized = _INDEXER.sub("[*]", selector)
    if normalized in fields:
        return fields[normalized]
    if ".." in normalized:  # recursive descent: match on the last segment
        last = normalized.rsplit("..", 1)[1]
        for path, kind in fields.items():
            if path.endswith("." + last) or path.endswith("[*]." + last):
                return kind
    return None if len(fields) >= MAX_FIELDS else ""


def _is_collection(selector: str, kind: str) -> bool:
    return "[*]" in _INDEXER.sub("[*]", selector) or ".." in selector or kind.startswith("array")


def _selector_violations(selector: str, op: OperationContext, spec: MRSpec) -> list[str]:
    where = f"{op.method.value} {op.path}"
    kind = field_type(selector, op)
    if kind is None:
        return []
    if kind == "":
        return [f"el selector '{selector}' no corresponde a ningún campo de la respuesta de {where}"]
    relation = spec.relation
    collection = _is_collection(selector, kind)
    if relation.type in COLLECTION_RELATIONS and not collection:
        return [f"la relación {relation.type.value} compara colecciones, pero '{selector}' devuelve un único valor"]
    if relation.type is RelationType.COUNT_LEQ and relation.measure is Measure.VALUE:
        if collection or kind not in ("integer", "number"):
            return [f"measure=value necesita un selector que devuelva un único número; '{selector}' es {kind}"]
    return []


def semantic_violations(spec: MRSpec, ctx: ApiContext) -> list[str]:
    """Rule violations (empty list = the MR is consistent with the spec)."""
    try:
        instances = spec.instances()
    except MRNotExecutableError as exc:  # already validated by MRSpec, kept as a safety net
        return [f"no se pueden derivar las peticiones: {exc}"]

    found: dict[str, None] = {}  # ordered set: variants repeat the same messages
    for source, followups in instances:
        for req in (source, *followups):
            found.update(dict.fromkeys(_request_violations(req, ctx)))

    base_source, base_followups = instances[0]
    selectors = [(spec.relation.source_selector, base_source)]
    selectors += [(spec.relation.effective_followup_selector, f) for f in base_followups]
    for selector, req in selectors:
        op = ctx.find_operation(req.method.value, req.path)
        if op is not None:
            found.update(dict.fromkeys(_selector_violations(selector, op, spec)))
    return list(found)[:MAX_VIOLATIONS]
