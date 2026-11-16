"""Anthropic Claude provider (official ``anthropic`` SDK, async, streaming).

* JSON is obtained with structured outputs (``output_config.format``), not forced
  tool use: ``tool_choice`` ``any``/``tool`` returns 400 on Claude Sonnet 5.5 and
  Claude Opus 5.5.
* Requests are streamed and collected with ``get_final_message()`` so large
  ``max_tokens`` values do not hit HTTP timeouts.
* On models that support it, server-side refusal fallbacks are enabled
  (``fallbacks: "default"``); the model that actually answered is reported in
  ``LLMResponse.model`` so provenance stays accurate.
* Credentials are resolved by the SDK from the environment (``ANTHROPIC_API_KEY``
  in backend/.env); they are never part of settings stored in MongoDB.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from app.pipeline.llm.base import LLMNotConfiguredError, LLMProviderError, LLMRequest, LLMResponse, TokenUsage

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept server-side refusal fallbacks (Claude Haiku 5.5 has none).
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5-2"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        client: Any | None = None,
        *,
        timeout: float = 600.0,
        max_retries: int = 2,
        enable_fallbacks: bool = True,
    ):
        self._client = client or anthropic.AsyncAnthropic(timeout=timeout, max_retries=max_retries)
        self.enable_fallbacks = enable_fallbacks

    def build_params(self, request: LLMRequest) -> tuple[dict[str, Any], bool]:
        """Request parameters and whether the beta endpoint (fallbacks) is used."""
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": request.json_schema}}
        if request.effort:
            output_config["effort"] = request.effort
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "output_config": output_config,
        }
        use_fallbacks = self.enable_fallbacks and request.model in FALLBACK_MODELS
        if use_fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params, use_fallbacks

    def _check_credentials(self) -> None:
        # Without this the SDK fails with a TypeError deep inside the request builder.
        missing = object()
        api_key = getattr(self._client, "api_key", missing)
        auth_token = getattr(self._client, "auth_token", missing)
        if api_key is None and auth_token is None:
            raise LLMNotConfiguredError("Anthropic: falta ANTHROPIC_API_KEY (agrégala en backend/.env)")

    async def complete_json(self, request: LLMRequest) -> LLMResponse:
        self._check_credentials()
        params, use_beta = self.build_params(request)
        messages = self._client.beta.messages if use_beta else self._client.messages
        try:
            async with messages.stream(**params) as stream:
                message = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise LLMProviderError(f"Anthropic: credenciales inválidas ({exc.message})") from exc
        except anthropic.BadRequestError as exc:
            raise LLMProviderError(f"Anthropic: petición inválida ({exc.message})") from exc
        except anthropic.RateLimitError as exc:
            raise LLMProviderError("Anthropic: límite de tasa excedido", retriable=True) from exc
        except anthropic.APIStatusError as exc:
            raise LLMProviderError(
                f"Anthropic: error {exc.status_code} ({exc.message})", retriable=exc.status_code >= 500
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError("Anthropic: error de conexión", retriable=True) from exc
        return self._to_response(message)

    def _to_response(self, message: Any) -> LLMResponse:
        blocks = list(getattr(message, "content", None) or [])
        text = "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text")
        data: Any | None = None
        if text:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
        usage = getattr(message, "usage", None)
        return LLMResponse(
            data=data,
            raw_text=text,
            model=getattr(message, "model", "") or "",
            provider=self.name,
            stop_reason=getattr(message, "stop_reason", None),
            usage=TokenUsage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            ),
            fallback_used=any(getattr(b, "type", None) == "fallback" for b in blocks),
        )
