"""Provider tests. The Anthropic SDK client is replaced by a fake: no network, no key."""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.pipeline.llm import (
    FakeLLMProvider,
    LLMNotConfiguredError,
    LLMProviderError,
    LLMRequest,
    LLMSettings,
    TokenUsage,
    create_provider,
)
from app.pipeline.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def request(model: str = "claude-sonnet-5-5", effort="medium") -> LLMRequest:
    return LLMRequest(system="sys", user="usr", json_schema=SCHEMA, model=model, max_tokens=2000, effort=effort)


def message(text: str, *, model="claude-sonnet-5-5", stop="end_turn", extra_blocks=()) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), *extra_blocks, SimpleNamespace(type="text", text=text)],
        model=model,
        stop_reason=stop,
        usage=SimpleNamespace(
            input_tokens=120, output_tokens=40, cache_read_input_tokens=None, cache_creation_input_tokens=0
        ),
    )


class FakeStream:
    def __init__(self, result):
        self.result = result

    async def __aenter__(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self.result


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    def stream(self, **params):
        self.calls.append(params)
        return FakeStream(self.result)


def fake_client(result) -> SimpleNamespace:
    return SimpleNamespace(messages=FakeMessages(result), beta=SimpleNamespace(messages=FakeMessages(result)))


@pytest.mark.asyncio
async def test_structured_output_request_with_fallbacks():
    client = fake_client(message('{"ok": true}'))
    resp = await AnthropicProvider(client).complete_json(request())

    assert client.messages.calls == []  # fallbacks need the beta endpoint
    params = client.beta.messages.calls[0]
    assert params["betas"] == [FALLBACK_BETA] and params["fallbacks"] == "default"
    assert params["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "medium"}
    assert params["system"] == "sys" and params["messages"] == [{"role": "user", "content": "usr"}]
    assert "tool_choice" not in params and "temperature" not in params and "thinking" not in params

    assert resp.data == {"ok": True} and resp.provider == "anthropic" and resp.stop_reason == "end_turn"
    assert resp.usage == TokenUsage(input_tokens=120, output_tokens=40)
    assert not resp.fallback_used


@pytest.mark.asyncio
async def test_models_without_fallbacks_use_the_regular_endpoint():
    client = fake_client(message('{"ok": false}', model="claude-haiku-5-5"))
    await AnthropicProvider(client).complete_json(request("claude-haiku-5-5", effort=None))
    params = client.messages.calls[0]
    assert "betas" not in params and "fallbacks" not in params
    assert params["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    assert client.beta.messages.calls == []


@pytest.mark.asyncio
async def test_fallbacks_can_be_disabled():
    client = fake_client(message('{"ok": true}'))
    await AnthropicProvider(client, enable_fallbacks=False).complete_json(request())
    assert client.beta.messages.calls == [] and "fallbacks" not in client.messages.calls[0]


@pytest.mark.asyncio
async def test_fallback_and_refusal_are_reported():
    served = message('{"ok": true}', model="claude-opus-5-5", extra_blocks=[SimpleNamespace(type="fallback")])
    resp = await AnthropicProvider(fake_client(served)).complete_json(request())
    assert resp.fallback_used and resp.model == "claude-opus-5-5"

    refused = await AnthropicProvider(fake_client(message("", stop="refusal"))).complete_json(request())
    assert refused.refused and refused.data is None


@pytest.mark.asyncio
async def test_invalid_json_keeps_raw_text():
    resp = await AnthropicProvider(fake_client(message('{"ok": tr', stop="max_tokens"))).complete_json(request())
    assert resp.data is None and resp.truncated and resp.raw_text == '{"ok": tr'


def _status_error(cls, status: int):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message="boom", response=httpx.Response(status, request=req), body=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc, retriable, text",
    [
        (lambda: _status_error(anthropic.AuthenticationError, 401), False, "credenciales"),
        (lambda: _status_error(anthropic.BadRequestError, 400), False, "petición inválida"),
        (lambda: _status_error(anthropic.RateLimitError, 429), True, "límite"),
        (lambda: _status_error(anthropic.InternalServerError, 500), True, "error 500"),
    ],
)
async def test_sdk_errors_are_mapped(exc, retriable, text):
    with pytest.raises(LLMProviderError, match=text) as info:
        await AnthropicProvider(fake_client(exc())).complete_json(request())
    assert info.value.retriable is retriable


@pytest.mark.asyncio
async def test_fake_provider_script():
    llm = FakeLLMProvider({"a": 1}, lambda r: {"model": r.model}, RuntimeError("down"))
    assert (await llm.complete_json(request())).data == {"a": 1}
    assert (await llm.complete_json(request("m2"))).data == {"model": "m2"}
    with pytest.raises(RuntimeError):
        await llm.complete_json(request())
    with pytest.raises(RuntimeError):  # last item repeats
        await llm.complete_json(request())
    assert len(llm.requests) == 4
    assert json.loads((await FakeLLMProvider([1, 2]).complete_json(request())).raw_text) == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["openai"])
async def test_stub_providers(name):
    provider = create_provider(LLMSettings(provider=name))
    assert provider.name == name
    with pytest.raises(LLMNotConfiguredError, match="no está implementado"):
        await provider.complete_json(request())


def test_factory_builds_anthropic_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    provider = create_provider(LLMSettings(enable_fallbacks=False))
    assert isinstance(provider, AnthropicProvider) and provider.enable_fallbacks is False
    with pytest.raises(LLMNotConfiguredError):
        create_provider(LLMSettings(provider="fake"))


def test_settings_defaults():
    s = LLMSettings()
    assert (s.generation_model, s.verification_model) == ("claude-sonnet-5-5", "claude-haiku-5-5")
    assert s.max_candidates == 20


@pytest.mark.asyncio
async def test_missing_api_key_is_a_clear_configuration_error():
    client = fake_client(message('{"ok": true}'))
    client.api_key, client.auth_token = None, None
    with pytest.raises(LLMNotConfiguredError, match="falta ANTHROPIC_API_KEY"):
        await AnthropicProvider(client).complete_json(request())
    assert client.beta.messages.calls == []  # nothing was sent


@pytest.mark.asyncio
async def test_pipeline_reports_missing_key_without_crashing(monkeypatch):
    from app.pipeline.orchestrator import StageName, StageStatus, run_pipeline
    from tests.conftest import FIXTURES

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    result = await run_pipeline(
        (FIXTURES / "openapi_search.yaml").read_text(encoding="utf-8"),
        project_id="p",
        run_id="r",
        provider=create_provider(LLMSettings()),
        embedder=None,
        sut=None,
    )
    assert result.report.error == "Anthropic: falta ANTHROPIC_API_KEY (agrégala en backend/.env)"
    assert result.report.stage(StageName.GENERATE).status is StageStatus.FAILED
