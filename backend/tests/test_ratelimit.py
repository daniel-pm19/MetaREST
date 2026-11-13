"""Client-side rate limiting and retry-after handling (fake clock, no real waiting)."""

from __future__ import annotations

import asyncio

import pytest

from app.pipeline.llm import FakeLLMProvider, LLMProviderError, LLMRequest, LLMSettings, create_provider
from app.pipeline.llm.ratelimit import RateLimitedProvider


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def req(model: str = "m") -> LLMRequest:
    return LLMRequest(system="s", user="u", json_schema={"type": "object"}, model=model)


def limited(*script, rpm: int = 12, **kw) -> tuple[RateLimitedProvider, FakeLLMProvider, Clock]:
    clock = Clock()
    inner = FakeLLMProvider(*script)
    return RateLimitedProvider(inner, rpm, clock=clock, sleep=clock.sleep, **kw), inner, clock


@pytest.mark.asyncio
async def test_requests_to_the_same_model_are_spaced():
    provider, inner, clock = limited({"ok": 1}, rpm=12)  # one request every 5 s
    await asyncio.gather(*(provider.complete_json(req()) for _ in range(3)))
    assert clock.sleeps == [5.0, 5.0] and clock.now == 10.0 and len(inner.requests) == 3
    await provider.complete_json(req("other"))  # each model has its own budget
    assert clock.sleeps == [5.0, 5.0]


@pytest.mark.asyncio
async def test_per_minute_quota_is_retried_after_the_given_delay():
    provider, inner, clock = limited(LLMProviderError("429", retriable=True, retry_after=20), {"ok": 1}, rpm=6000)
    resp = await provider.complete_json(req())
    assert resp.data == {"ok": 1} and 20 in clock.sleeps and len(inner.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        LLMProviderError("daily quota"),  # not retriable
        LLMProviderError("429", retriable=True),  # no delay given: the SDK already retried
        LLMProviderError("429", retriable=True, retry_after=48000),  # too long to wait
    ],
)
async def test_errors_that_are_not_waited_for(error):
    provider, inner, _ = limited(error, rpm=6000)
    with pytest.raises(LLMProviderError):
        await provider.complete_json(req())
    assert len(inner.requests) == 1


@pytest.mark.asyncio
async def test_gives_up_after_the_retries():
    provider, inner, _ = limited(LLMProviderError("429", retriable=True, retry_after=1), rpm=6000, retries=2)
    with pytest.raises(LLMProviderError):
        await provider.complete_json(req())
    assert len(inner.requests) == 3


def test_settings_default_rate_per_provider(monkeypatch):
    assert LLMSettings(provider="gemini").requests_per_minute == 12
    assert LLMSettings().requests_per_minute is None
    assert LLMSettings(provider="gemini", requests_per_minute=None).requests_per_minute is None  # paid tier
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    assert isinstance(create_provider(LLMSettings(provider="gemini")), RateLimitedProvider)
    assert not isinstance(
        create_provider(LLMSettings(provider="gemini", requests_per_minute=None)), RateLimitedProvider
    )
