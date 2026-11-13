"""LLM wire format: Pydantic JSON Schema → schema accepted by structured outputs.

Structured outputs accept a JSON Schema subset: no free-form maps
(``additionalProperties`` with a schema), no ``oneOf``, and no string/number/array
constraints. This module:

1. converts free-form maps (``query_params``, ``path_params``) into arrays of
   ``{"name", "value"}`` pairs, which the API supports;
2. drops unsupported keywords (Pydantic still enforces them when validating);
3. turns ``oneOf`` into ``anyOf`` and forces ``additionalProperties: false``;

and converts the LLM output back (pairs → maps) before ``MRSpec`` validation.
The MR contract itself (app/models/mr.py) is unchanged.
"""

from __future__ import annotations

import copy
from typing import Any

from app.models.mr import MRGenerationOutput

UNSUPPORTED_KEYWORDS = {
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "discriminator",
    "default",
    "title",
}

# Free-form maps of the contract that are sent to the LLM as [{name, value}] lists.
MAP_FIELDS = frozenset({"path_params", "query_params"})


class WireSchemaError(ValueError):
    pass


def _is_map(schema: Any) -> bool:
    return (
        isinstance(schema, dict)
        and schema.get("type") == "object"
        and isinstance(schema.get("additionalProperties"), dict)
        and not schema.get("properties")
    )


def _pairs_schema(value_schema: dict[str, Any], description: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "value": value_schema},
            "required": ["name", "value"],
            "additionalProperties": False,
        },
    }
    if description:
        out["description"] = f"{description} List of {{name, value}} pairs."
    return out


def to_api_schema(schema: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Return (api_schema, names_of_converted_map_properties)."""
    converted: set[str] = set()

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in UNSUPPORTED_KEYWORDS:
                continue
            if key in ("properties", "$defs"):
                props: dict[str, Any] = {}
                for name, sub in value.items():
                    if key == "properties" and _is_map(sub):
                        converted.add(name)
                        props[name] = _pairs_schema(walk(sub["additionalProperties"]), sub.get("description"))
                    else:
                        props[name] = walk(sub)
                out[key] = props
                continue
            out["anyOf" if key == "oneOf" else key] = walk(value)
        if _is_map(out):
            raise WireSchemaError("free-form map outside a named property cannot be expressed")
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
        return out

    api_schema = walk(copy.deepcopy(schema))
    if converted - MAP_FIELDS:
        raise WireSchemaError(f"unexpected map fields {sorted(converted - MAP_FIELDS)}: extend MAP_FIELDS/from_wire")
    return api_schema, converted


def generation_schema() -> dict[str, Any]:
    """Schema sent as ``output_config.format`` during MR generation."""
    schema, _ = to_api_schema(MRGenerationOutput.model_json_schema())
    return schema


def from_wire(value: Any) -> Any:
    """Inverse of the map → pairs conversion, applied to raw LLM output.

    Malformed pairs are left untouched so that ``MRSpec`` validation reports them.
    """
    if isinstance(value, list):
        return [from_wire(v) for v in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, sub in value.items():
        if (
            key in MAP_FIELDS
            and isinstance(sub, list)
            and all(isinstance(p, dict) and set(p) == {"name", "value"} and isinstance(p["name"], str) for p in sub)
        ):
            out[key] = {p["name"]: p["value"] for p in sub}
        else:
            out[key] = from_wire(sub)
    return out


def to_wire(value: Any) -> Any:
    """Maps → pairs (used to build few-shot examples and tests)."""
    if isinstance(value, list):
        return [to_wire(v) for v in value]
    if not isinstance(value, dict):
        return value
    return {
        k: [{"name": n, "value": v} for n, v in sub.items()]
        if k in MAP_FIELDS and isinstance(sub, dict)
        else to_wire(sub)
        for k, sub in value.items()
    }
