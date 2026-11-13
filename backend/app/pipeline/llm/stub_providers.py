"""Placeholders that keep the multi-provider design explicit.

They satisfy ``LLMProvider`` so the factory, settings and UI can list them, but the
MVP only implements Anthropic. Implementing one = filling ``complete_json`` with that
vendor's structured-output call and mapping its usage/stop reason to ``LLMResponse``.
"""

from __future__ import annotations

from app.pipeline.llm.base import LLMNotConfiguredError, LLMRequest, LLMResponse


class _NotImplementedProvider:
    name = "unimplemented"

    async def complete_json(self, request: LLMRequest) -> LLMResponse:
        raise LLMNotConfiguredError(f"el proveedor '{self.name}' no está implementado en el MVP")


class OpenAIProvider(_NotImplementedProvider):
    name = "openai"


class GeminiProvider(_NotImplementedProvider):
    name = "gemini"
