"""OpenAPI → compact ``ApiContext`` used by the generator prompt and the semantic rules.

Supports OpenAPI 3.0 / 3.1 and Swagger 2.0 documents (JSON or YAML). Only safe
operations (GET/HEAD) are extracted, since those are the only ones MetaREST executes.
Local ``$ref``s are resolved with cycle protection; remote refs are left unresolved.

Every free-text field coming from the spec (summaries, descriptions) is untrusted:
it is sanitized and truncated here, and must be delimited again in the prompt.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.models.mr import HttpMethod, path_placeholders

SAFE_METHODS = ("get", "head")
ALL_METHODS = ("get", "head", "post", "put", "patch", "delete", "options", "trace")
SUCCESS_CODES = ("200", "203", "206", "2XX", "2xx")  # then any other 2xx, then "default"

MAX_TEXT = 200
MAX_DEPTH = 5
MAX_FIELDS = 80

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class SpecError(ValueError):
    """The document is not a usable OpenAPI/Swagger spec."""


# ─────────────────────────────── Models ──────────────────────────────────


class ParamContext(BaseModel):
    name: str
    location: str  # "query" | "path"
    required: bool = False
    type: str = "string"  # string | integer | number | boolean | array | object
    items_type: str | None = None
    enum: list[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    default: Any | None = None
    example: Any | None = None
    description: str | None = None


class OperationContext(BaseModel):
    method: HttpMethod
    path: str
    operation_id: str | None = None
    summary: str | None = None
    parameters: list[ParamContext] = Field(default_factory=list)
    unsupported_params: list[str] = Field(
        default_factory=list, description="header/cookie/body params the executor cannot set."
    )
    response_shape: Any | None = Field(default=None, description="Compact type tree of the success response.")
    response_fields: dict[str, str] = Field(
        default_factory=dict, description="JSONPath -> type, e.g. {'$.results[*].id': 'integer'}."
    )

    def param(self, name: str, location: str | None = None) -> ParamContext | None:
        return next(
            (p for p in self.parameters if p.name == name and (location is None or p.location == location)),
            None,
        )


class ApiContext(BaseModel):
    title: str
    version: str | None = None
    spec_version: str
    servers: list[str] = Field(default_factory=list)
    operations: list[OperationContext] = Field(default_factory=list)
    skipped_operations: int = Field(default=0, description="Non-safe operations ignored (POST, PUT, ...).")

    def find_operation(self, method: str, path: str) -> OperationContext | None:
        method = method.upper()
        return next((op for op in self.operations if op.method == method and op.path == path), None)

    def to_prompt_text(self) -> str:
        """Compact, deterministic rendering for the LLM prompt (descriptions are untrusted data)."""
        lines = [f"API: {self.title} (version {self.version or 'n/a'})"]
        for op in self.operations:
            lines.append(f"\n## {op.method.value} {op.path}" + (f"  [{op.operation_id}]" if op.operation_id else ""))
            if op.summary:
                lines.append(f"summary: {op.summary}")
            for p in op.parameters:
                attrs = [p.location, p.type + (f"<{p.items_type}>" if p.items_type else "")]
                if p.required:
                    attrs.append("required")
                if p.enum:
                    attrs.append(f"enum={json.dumps(p.enum, ensure_ascii=False)}")
                if p.minimum is not None:
                    attrs.append(f"min={_num(p.minimum)}")
                if p.maximum is not None:
                    attrs.append(f"max={_num(p.maximum)}")
                if p.default is not None:
                    attrs.append(f"default={json.dumps(p.default, ensure_ascii=False)}")
                if p.example is not None:
                    attrs.append(f"example={json.dumps(p.example, ensure_ascii=False)}")
                desc = f" — {p.description}" if p.description else ""
                lines.append(f"- param {p.name} ({', '.join(attrs)}){desc}")
            if op.response_fields:
                lines.append("response fields: " + ", ".join(f"{k}: {v}" for k, v in op.response_fields.items()))
        return "\n".join(lines)


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


# ─────────────────────────────── Loading ─────────────────────────────────


def load_spec(raw: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Parse a JSON/YAML OpenAPI document (YAML is a superset of JSON)."""
    if isinstance(raw, dict):
        doc = raw
    else:
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise SpecError(f"spec is not valid JSON/YAML: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        raise SpecError("spec must be an object with a 'paths' section")
    if not (str(doc.get("openapi", "")).startswith("3") or str(doc.get("swagger", "")) == "2.0"):
        raise SpecError("only OpenAPI 3.x and Swagger 2.0 are supported")
    return doc


def sanitize_text(text: Any, limit: int = MAX_TEXT) -> str | None:
    if not isinstance(text, str):
        return None
    clean = _CONTROL.sub(" ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return None
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


# ─────────────────────────────── $ref ────────────────────────────────────


class _Resolver:
    def __init__(self, doc: dict[str, Any]):
        self.doc = doc

    def resolve(self, node: Any, seen: frozenset[str] = frozenset()) -> tuple[Any, frozenset[str]]:
        """Follow a chain of local $refs. Returns (node, refs_seen). Cycles yield {}."""
        while isinstance(node, dict) and isinstance(node.get("$ref"), str):
            ref = node["$ref"]
            if ref in seen or not ref.startswith("#/"):
                return {}, seen
            seen = seen | {ref}
            node = self._lookup(ref)
        return node, seen

    def _lookup(self, ref: str) -> Any:
        cur: Any = self.doc
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(cur, dict) or part not in cur:
                return {}
            cur = cur[part]
        return cur


# ─────────────────────────────── Schemas ─────────────────────────────────


def _schema_type(schema: dict[str, Any]) -> str:
    t = schema.get("type")
    if isinstance(t, list):  # OpenAPI 3.1: ["integer", "null"]
        t = next((x for x in t if x != "null"), None)
    if t:
        return str(t)
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return "any"


def _merge_composed(schema: dict[str, Any], resolver: _Resolver, seen: frozenset[str]) -> dict[str, Any]:
    """allOf → merged properties; oneOf/anyOf → first alternative (good enough for a summary)."""
    if "allOf" in schema:
        merged: dict[str, Any] = {"type": "object", "properties": {}}
        for part in schema["allOf"]:
            sub, sub_seen = resolver.resolve(part, seen)
            sub = _merge_composed(sub, resolver, sub_seen) if isinstance(sub, dict) else {}
            merged["properties"].update(sub.get("properties", {}))
            if "items" in sub:
                merged = {**merged, "type": "array", "items": sub["items"]}
        return merged
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            sub, sub_seen = resolver.resolve(schema[key][0], seen)
            return _merge_composed(sub, resolver, sub_seen) if isinstance(sub, dict) else {}
    return schema


def summarize_schema(
    schema: Any,
    resolver: _Resolver,
    seen: frozenset[str] = frozenset(),
    depth: int = 0,
) -> Any:
    """Compact type tree: {"total": "integer", "results": [{"id": "integer"}]}."""
    schema, seen = resolver.resolve(schema, seen)
    if not isinstance(schema, dict) or not schema:
        return "any"
    schema = _merge_composed(schema, resolver, seen)
    kind = _schema_type(schema)
    if depth >= MAX_DEPTH:
        return kind
    if kind == "array":
        return [summarize_schema(schema.get("items", {}), resolver, seen, depth + 1)]
    if kind == "object":
        props = schema.get("properties") or {}
        if not props:
            return "object"
        return {name: summarize_schema(sub, resolver, seen, depth + 1) for name, sub in props.items()}
    return kind


def shape_fields(shape: Any, prefix: str = "$") -> dict[str, str]:
    """Flatten a shape into selectable JSONPaths, e.g. '$.results[*].id' -> 'integer'."""
    fields: dict[str, str] = {}

    def walk(node: Any, path: str) -> None:
        if len(fields) >= MAX_FIELDS:
            return
        if isinstance(node, list):
            inner = node[0] if node else "any"
            fields[path] = f"array<{_describe(inner)}>"
            walk(inner, f"{path}[*]")
        elif isinstance(node, dict):
            if path != prefix:
                fields[path] = "object"
            for name, sub in node.items():
                key = name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else f"'{name}'"
                walk(sub, f"{path}.{key}" if not key.startswith("'") else f"{path}[{key}]")
        else:
            if path != prefix:
                fields[path] = str(node)

    walk(shape, prefix)
    return fields


def _describe(node: Any) -> str:
    if isinstance(node, list):
        return "array"
    if isinstance(node, dict):
        return "object"
    return str(node)


# ─────────────────────────────── Operations ──────────────────────────────


def _param_context(raw: dict[str, Any], resolver: _Resolver, swagger2: bool) -> ParamContext | None:
    location = raw.get("in")
    if location not in ("query", "path"):
        return None
    schema: dict[str, Any] = raw if swagger2 else (resolver.resolve(raw.get("schema", {}))[0] or {})
    if not isinstance(schema, dict):
        schema = {}
    schema = _merge_composed(schema, resolver, frozenset())
    items, _ = resolver.resolve(schema.get("items", {}))
    example = raw.get("example", schema.get("example"))
    if example is None and isinstance(raw.get("examples"), dict) and raw["examples"]:
        first = next(iter(raw["examples"].values()))
        first, _ = resolver.resolve(first)
        example = first.get("value") if isinstance(first, dict) else None
    return ParamContext(
        name=str(raw.get("name")),
        location=location,
        required=bool(raw.get("required", location == "path")),
        type=_schema_type(schema) if schema else "string",
        items_type=_schema_type(items) if isinstance(items, dict) and items else None,
        enum=schema.get("enum"),
        minimum=schema.get("minimum"),
        maximum=schema.get("maximum"),
        default=schema.get("default"),
        example=example,
        description=sanitize_text(raw.get("description")),
    )


def _success_schema(op: dict[str, Any], resolver: _Resolver, swagger2: bool) -> Any | None:
    responses = op.get("responses") or {}
    for code in (*SUCCESS_CODES, *sorted(str(c) for c in responses if str(c) != "default"), "default"):
        resp = responses.get(code) if code in responses else responses.get(_int_or_none(code))
        if resp is None or not (code.startswith("2") or code in ("2XX", "2xx", "default")):
            continue
        resp, _ = resolver.resolve(resp)
        if not isinstance(resp, dict):
            continue
        if swagger2:
            if "schema" in resp:
                return resp["schema"]
            continue
        content = resp.get("content") or {}
        media = next((m for m in content if "json" in m), next(iter(content), None))
        if media and isinstance(content[media], dict) and "schema" in content[media]:
            return content[media]["schema"]
    return None


def _int_or_none(code: str) -> int | None:
    return int(code) if code.isdigit() else None  # YAML may load status codes as ints


def extract_context(raw: str | bytes | dict[str, Any]) -> ApiContext:
    doc = load_spec(raw)
    swagger2 = str(doc.get("swagger", "")) == "2.0"
    resolver = _Resolver(doc)
    info = doc.get("info") or {}

    if swagger2:
        scheme = (doc.get("schemes") or ["https"])[0]
        host = doc.get("host")
        servers = [f"{scheme}://{host}{doc.get('basePath', '')}"] if host else []
    else:
        servers = [s["url"] for s in doc.get("servers") or [] if isinstance(s, dict) and "url" in s]

    operations: list[OperationContext] = []
    skipped = 0
    for path, item in doc["paths"].items():
        item, _ = resolver.resolve(item)
        if not isinstance(item, dict) or not str(path).startswith("/"):
            continue
        shared = item.get("parameters") or []
        for method in ALL_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            if method not in SAFE_METHODS:
                skipped += 1
                continue
            operations.append(_operation_context(str(path), method, op, shared, resolver, swagger2))

    return ApiContext(
        title=sanitize_text(info.get("title")) or "Untitled API",
        version=str(info["version"]) if "version" in info else None,
        spec_version=str(doc.get("openapi") or doc.get("swagger")),
        servers=servers,
        operations=operations,
        skipped_operations=skipped,
    )


def _operation_context(
    path: str,
    method: str,
    op: dict[str, Any],
    shared: list[Any],
    resolver: _Resolver,
    swagger2: bool,
) -> OperationContext:
    # Operation-level params override path-level ones with the same (name, in).
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*shared, *(op.get("parameters") or [])]:
        raw, _ = resolver.resolve(raw)
        if isinstance(raw, dict) and "name" in raw:
            by_key[(str(raw["name"]), str(raw.get("in")))] = raw

    params: list[ParamContext] = []
    unsupported: list[str] = []
    for (name, location), raw in by_key.items():
        ctx = _param_context(raw, resolver, swagger2)
        if ctx is None:
            if raw.get("required"):
                unsupported.append(f"{location}:{name}")
            continue
        params.append(ctx)

    # Placeholders without a declared parameter still need a value.
    declared = {p.name for p in params if p.location == "path"}
    for missing in sorted(path_placeholders(path) - declared):
        params.append(ParamContext(name=missing, location="path", required=True))

    schema = _success_schema(op, resolver, swagger2)
    shape = summarize_schema(schema, resolver) if schema is not None else None
    return OperationContext(
        method=HttpMethod(method.upper()),
        path=path,
        operation_id=sanitize_text(op.get("operationId"), 100),
        summary=sanitize_text(op.get("summary") or op.get("description")),
        parameters=params,
        unsupported_params=unsupported,
        response_shape=shape,
        response_fields=shape_fields(shape) if shape is not None else {},
    )
