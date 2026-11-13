"""Gemini provider tests. The google-genai client is replaced by a fake: no network, no key."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types

from app.pipeline.llm import LLMNotConfiguredError, LLMProviderError, LLMRequest, LLMSettings, create_provider
from app.pipeline.llm.gemini_provider import GeminiProvider, to_gemini_schema
from app.pipeline.wire import generation_schema

SCHEMA = {
    "type": "object",
    "properties": {"op": {"type": "string", "const": "set_param"}, "const": {"type": "integer"}},
    "required": ["op", "const"],
    "additionalProperties": False,
}


def request(model: str = "gemini-4-hydrogen", effort="medium") -> LLMRequest:
    return LLMRequest(system="sys", user="usr", json_schema=SCHEMA, model=model, max_tokens=2000, effort=effort)


def response(text: str = '{"op": "set_param", "const": 1}', finish="STOP", *, blocked=None, thought=False):
    parts = [SimpleNamespace(text="pensando…", thought=True)] if thought else []
    parts.append(SimpleNamespace(text=text, thought=None))
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts), finish_reason=types.FinishReason(finish))],
        prompt_feedback=SimpleNamespace(block_reason=blocked) if blocked else None,
        model_version="gemini-4-hydrogen-001",
        usage_metadata=SimpleNamespace(
            prompt_token_count=120, cached_content_token_count=20, candidates_token_count=40, thoughts_token_count=10
        ),
    )


class FakeModels:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def provider(result) -> tuple[GeminiProvider, FakeModels]:
    models = FakeModels(result)
    return GeminiProvider(SimpleNamespace(aio=SimpleNamespace(models=models))), models


@pytest.mark.asyncio
async def test_structured_output_request_and_response():
    llm, models = provider(response(thought=True))
    resp = await llm.complete_json(request())

    call = models.calls[0]
    assert (call["model"], call["contents"]) == ("gemini-4-hydrogen", "usr")
    config = call["config"]
    assert config["system_instruction"] == "sys" and config["max_output_tokens"] == 2000
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"]["properties"]["op"] == {"type": "string", "enum": ["set_param"]}
    assert config["thinking_config"] == {"thinking_level": "MEDIUM"}
    assert "temperature" not in config

    assert resp.data == {"op": "set_param", "const": 1}  # the thought part is not part of the answer
    assert (resp.provider, resp.model, resp.stop_reason) == ("gemini", "gemini-4-hydrogen-001", "end_turn")
    assert (resp.usage.input_tokens, resp.usage.output_tokens, resp.usage.cache_read_input_tokens) == (100, 50, 20)


def test_schema_conversion_keeps_field_names():
    converted = to_gemini_schema(SCHEMA)
    assert "const" in converted["properties"]  # a property called "const" is a name, not the keyword
    assert converted["properties"]["const"] == {"type": "integer"}
    assert SCHEMA["properties"]["op"]["const"] == "set_param"  # input untouched

    def keywords(node) -> set[str]:
        if isinstance(node, list):
            return set().union(*(keywords(n) for n in node)) if node else set()
        if not isinstance(node, dict):
            return set()
        found = set(node) - {"properties", "$defs"}
        for key, value in node.items():
            children = value.values() if key in ("properties", "$defs") else [value]
            found |= set().union(*(keywords(c) for c in children)) if children else set()
        return found

    assert "const" not in keywords(to_gemini_schema(generation_schema()))


@pytest.mark.parametrize(
    "model, effort, level",
    [
        ("gemini-4-hydrogen", "xhigh", "XHIGH"),
        ("gemini-4-hydrogen", "max", "XHIGH"),
        ("gemini-3.5-flash-lite", "xhigh", "HIGH"),
        ("gemini-3.5-flash-lite", "low", "LOW"),
    ],
)
def test_effort_maps_to_thinking_level(model, effort, level):
    assert GeminiProvider.build_config(request(model, effort))["thinking_config"] == {"thinking_level": level}
    assert "thinking_config" not in GeminiProvider.build_config(request(model, None))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result, stop, truncated, refused",
    [
        (response('{"op": "set', "MAX_TOKENS"), "max_tokens", True, False),
        (response("", "SAFETY"), "refusal", False, True),
        (response("{}", blocked=types.BlockedReason("PROHIBITED_CONTENT")), "refusal", False, True),
    ],
)
async def test_truncation_and_refusals(result, stop, truncated, refused):
    resp = await provider(result)[0].complete_json(request())
    assert resp.stop_reason == stop and resp.truncated is truncated and resp.refused is refused


@pytest.mark.asyncio
async def test_no_candidates_is_not_a_crash():
    empty = SimpleNamespace(candidates=None, prompt_feedback=None, model_version=None, usage_metadata=None)
    resp = await provider(empty)[0].complete_json(request())
    assert resp.data is None and resp.model == "gemini-4-hydrogen" and resp.usage.total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc, retriable, text",
    [
        (
            errors.ClientError(401, {"error": {"message": "bad key", "status": "UNAUTHENTICATED"}}),
            False,
            "credenciales",
        ),
        (errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}), True, "límite"),
        (errors.ClientError(404, {"error": {"message": "nope", "status": "NOT_FOUND"}}), False, "no existe"),
        (errors.ClientError(400, {"error": {"message": "schema", "status": "INVALID_ARGUMENT"}}), False, "inválida"),
        (errors.ServerError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}}), True, "error 503"),
        (httpx.ConnectError("down"), True, "conexión"),
    ],
)
async def test_sdk_errors_are_mapped(exc, retriable, text):
    with pytest.raises(LLMProviderError, match=text) as info:
        await provider(exc)[0].complete_json(request())
    assert info.value.retriable is retriable


@pytest.mark.asyncio
async def test_missing_key_is_a_configuration_error(monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(var, raising=False)
    gemini = create_provider(LLMSettings(provider="gemini"))
    with pytest.raises(LLMNotConfiguredError, match="falta GEMINI_API_KEY"):
        await gemini.complete_json(request())


def test_settings_pick_provider_default_models():
    s = LLMSettings(provider="gemini")
    assert (s.generation_model, s.verification_model) == ("gemini-4-hydrogen", "gemini-3.5-flash-lite")
    custom = LLMSettings(provider="gemini", generation_model="gemini-4-argon")
    assert (custom.generation_model, custom.verification_model) == ("gemini-4-argon", "gemini-3.5-flash-lite")
    assert LLMSettings().generation_model == "claude-sonnet-5-5"
    restored = LLMSettings.model_validate(s.model_dump())  # what the backend stores and reloads
    assert restored == s
