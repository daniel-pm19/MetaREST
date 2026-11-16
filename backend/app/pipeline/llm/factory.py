from __future__ import annotations

from app.pipeline.llm.base import LLMNotConfiguredError, LLMProvider
from app.pipeline.llm.config import LLMSettings
from app.pipeline.llm.ratelimit import RateLimitedProvider
from app.pipeline.llm.stub_providers import OpenAIProvider


def create_provider(settings: LLMSettings) -> LLMProvider:
    """Build the provider selected by the Administrator (rate-limited when ``requests_per_minute`` is set)."""
    provider = _base_provider(settings)
    if settings.requests_per_minute:
        return RateLimitedProvider(provider, settings.requests_per_minute)
    return provider


def _base_provider(settings: LLMSettings) -> LLMProvider:
    match settings.provider:
        case "anthropic":
            from app.pipeline.llm.anthropic_provider import AnthropicProvider  # SDK imported only when used

            return AnthropicProvider(
                timeout=settings.timeout_seconds,
                max_retries=settings.max_retries,
                enable_fallbacks=settings.enable_fallbacks,
            )
        case "openai":
            return OpenAIProvider()
        case "gemini":
            from app.pipeline.llm.gemini_provider import GeminiProvider  # SDK imported only when used

            return GeminiProvider(timeout=settings.timeout_seconds, max_retries=settings.max_retries)
        case "fake":
            raise LLMNotConfiguredError("el proveedor 'fake' solo se usa en tests; instáncialo directamente")
    raise LLMNotConfiguredError(f"proveedor desconocido: {settings.provider}")  # pragma: no cover
