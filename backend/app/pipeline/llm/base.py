"""Provider-agnostic LLM interface.

The pipeline only needs one capability: "given a system prompt, a user prompt and a
JSON Schema, return JSON that follows the schema". Every provider implements it;
the rest of the pipeline never imports a vendor SDK.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other.cache_creation_input_tokens,
        )

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens


class LLMRequest(BaseModel):
    system: str
    user: str
    json_schema: dict[str, Any] = Field(description="API-compatible JSON Schema (see app.pipeline.wire).")
    model: str
    max_tokens: int = 32000
    effort: Effort | None = None


class LLMResponse(BaseModel):
    data: Any | None = Field(default=None, description="Parsed JSON, or None if the text was not valid JSON.")
    raw_text: str = ""
    model: str = Field(description="Model that actually served the request (may differ after a fallback).")
    provider: str
    stop_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    fallback_used: bool = False

    @property
    def refused(self) -> bool:
        return self.stop_reason == "refusal"

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "max_tokens"


class LLMProviderError(RuntimeError):
    """The provider could not produce a response (network, auth, rate limit after retries, ...)."""

    def __init__(self, message: str, *, retriable: bool = False):
        super().__init__(message)
        self.retriable = retriable


class LLMNotConfiguredError(LLMProviderError):
    """Provider selected in settings but not implemented / missing credentials."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete_json(self, request: LLMRequest) -> LLMResponse: ...
