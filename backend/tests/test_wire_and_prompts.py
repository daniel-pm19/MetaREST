from __future__ import annotations

import json

import pytest

from app.models.mr import MRSpec
from app.pipeline.prompts import PromptTemplate, available_prompts
from app.pipeline.wire import (
    MAP_FIELDS,
    UNSUPPORTED_KEYWORDS,
    WireSchemaError,
    from_wire,
    generation_schema,
    to_api_schema,
    to_wire,
)
from tests.conftest import EXAMPLES, load_example


def walk(node):
    yield node
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "properties":
                for sub in v.values():
                    yield from walk(sub)
            else:
                yield from walk(v)
    elif isinstance(node, list):
        for x in node:
            yield from walk(x)


def test_generation_schema_only_uses_supported_features():
    schema = generation_schema()
    for node in walk(schema):
        if not isinstance(node, dict):
            continue
        assert not (UNSUPPORTED_KEYWORDS & node.keys() - {"title"}), node
        assert "oneOf" not in node
        if node.get("type") == "object" or "properties" in node:
            assert node.get("additionalProperties") is False, node
    assert '"POST"' not in json.dumps(schema)


def test_property_named_title_survives_keyword_stripping():
    spec_def = generation_schema()["$defs"]["MRSpec"]
    assert "title" in spec_def["properties"]
    assert "title" in spec_def["required"]


def test_maps_become_name_value_pairs():
    schema, converted = to_api_schema(MRSpec.model_json_schema())
    assert converted == MAP_FIELDS
    qp = schema["$defs"]["RequestSpec"]["properties"]["query_params"]
    assert qp["type"] == "array"
    assert qp["items"]["required"] == ["name", "value"]


def test_unexpected_map_fields_are_rejected():
    schema = {
        "type": "object",
        "properties": {"headers": {"type": "object", "additionalProperties": {"type": "string"}}},
    }
    with pytest.raises(WireSchemaError, match="headers"):
        to_api_schema(schema)


@pytest.mark.parametrize("path", sorted((EXAMPLES / "specs").glob("*.json")), ids=lambda p: p.name)
def test_wire_roundtrip_on_examples(path):
    spec = load_example(path.name)
    wire = to_wire(spec)
    assert isinstance(wire["source"]["query_params"], list)
    assert from_wire(wire) == spec
    MRSpec.model_validate(from_wire(wire))


def test_from_wire_leaves_malformed_pairs_for_validation():
    bad = {"query_params": [{"name": "q"}]}
    assert from_wire(bad) == bad


def test_gen_v1_renders_and_is_registered():
    assert "gen_v1" in available_prompts()
    prompt = PromptTemplate.builtin("gen_v1").render(api_context="## GET /search", n=7)
    assert prompt.prompt_id == "gen_v1"
    assert "<api_spec>\n## GET /search\n</api_spec>" in prompt.user
    assert "exactly 7" in prompt.user
    for word in ("set_param", "move_param", "count_leq", "same_order", "untrusted"):
        assert word in prompt.system


def test_prompt_variables_are_strict():
    with pytest.raises(Exception, match="api_context"):
        PromptTemplate.builtin("gen_v1").render(n=3)
    with pytest.raises(KeyError):
        PromptTemplate.builtin("gen_v99")
