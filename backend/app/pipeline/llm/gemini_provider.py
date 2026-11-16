"""Google Gemini provider (official ``google-genai`` SDK, async).

* JSON via ``response_mime_type="application/json"`` + ``response_json_schema``
  (Gemini structured output). It accepts a JSON Schema subset; the schema the
  pipeline sends (already adapted by ``app.pipeline.wire``) only needs ``const``
  turned into a one-value ``enum``. Pydantic still validates every output.
* ``effort`` maps to ``thinking_config.thinking_level``. ``xhigh`` exists only on
  Gemini 4 Hydrogen; other models get ``high``.
* Retries (408/429/5xx) are delegated to the SDK's ``HttpRetryOptions``.
* The key is read by the SDK from ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY``) in
  backend/.env; it is never part of the settings stored in MongoDB.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

import httpx
from google.genai import errors

from app.pipeline.llm.base import LLMNotConfiguredError, LLMProviderError, LLMRequest, LLMResponse, TokenUsage

_LEVELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "XHIGH", "max": "XHIGH"}
XHIGH_MODELS = {"gemini-4-hydrogen"}

# finish_reason -> our stop_reason ("end_turn" / "max_tokens" / "refusal" like Anthropic's)
_STOP = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"}
KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_GENAI_USE_VERTEXAI")
REFUSAL_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "MODEL_ARMOR"}


def to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """``{"const": v}`` -> ``{"enum": [v]}`` everywhere (the rest is already in Gemini's subset)."""

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(v) for v in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "const":
                out["enum"] = [value]
            elif key in ("properties", "$defs"):  # keys are names, not keywords (a field may be called "const")
                out[key] = {name: walk(sub) for name, sub in value.items()}
            else:
                out[key] = walk(value)
        return out

    return walk(copy.deepcopy(schema))


def _quota(exc: errors.APIError) -> tuple[bool, str | None, float | None]:
    """(per-day quota?, its limit, seconds to wait) from a 429's ``QuotaFailure`` / ``RetryInfo`` details."""
    error = exc.details.get("error", {}) if isinstance(exc.details, dict) else {}
    per_day, limit, retry = False, None, None
    for detail in error.get("details", []) if isinstance(error, dict) else []:
        for violation in detail.get("violations", []) or []:
            if "PerDay" in str(violation.get("quotaId", "")):
                per_day, limit = True, violation.get("quotaValue") or limit
        delay = str(detail.get("retryDelay", ""))
        if delay.endswith("s"):
            try:
                retry = float(delay[:-1])
            except ValueError:
                pass
    return per_day, limit, retry


def _name(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


class GeminiProvider:
    name = "gemini"

    def __init__(self, client: Any | None = None, *, timeout: float = 600.0, max_retries: int = 2):
        self._client = client
        self.timeout = timeout
        self.max_retries = max_retries

    def _aio(self) -> Any:
        if self._client is None:
            # Checked before building the client: when the SDK constructor fails it leaves a
            # pending aclose() task that prints a spurious traceback.
            if not any(os.environ.get(var) for var in KEY_VARS):
                raise LLMNotConfiguredError("Gemini: falta GEMINI_API_KEY (agrégala en backend/.env)")
            from google import genai
            from google.genai import types

            options = types.HttpOptions(
                timeout=int(self.timeout * 1000),
                retry_options=types.HttpRetryOptions(attempts=self.max_retries + 1),
            )
            try:
                self._client = genai.Client(http_options=options)
            except ValueError as exc:  # raised by the SDK when no key is configured
                raise LLMNotConfiguredError("Gemini: falta GEMINI_API_KEY (agrégala en backend/.env)") from exc
        return self._client.aio

    @staticmethod
    def build_config(request: LLMRequest) -> dict[str, Any]:
        config: dict[str, Any] = {
            "system_instruction": request.system,
            "max_output_tokens": request.max_tokens,
            "response_mime_type": "application/json",
            "response_json_schema": to_gemini_schema(request.json_schema),
        }
        if request.effort:
            level = _LEVELS[request.effort]
            if level == "XHIGH" and request.model not in XHIGH_MODELS:
                level = "HIGH"
            config["thinking_config"] = {"thinking_level": level}
        return config

    async def complete_json(self, request: LLMRequest) -> LLMResponse:
        aio = self._aio()
        try:
            response = await aio.models.generate_content(
                model=request.model, contents=request.user, config=self.build_config(request)
            )
        except errors.ClientError as exc:
            if exc.code in (401, 403):
                raise LLMProviderError(f"Gemini: credenciales inválidas ({exc.message})") from exc
            if exc.code == 429:
                per_day, limit, retry = _quota(exc)
                if per_day:
                    hours = f"; se reinicia en ~{retry / 3600:.0f} h" if retry else ""
                    raise LLMProviderError(
                        f"Gemini: cuota diaria agotada para {request.model} ({limit or '?'} peticiones/día){hours}"
                    ) from exc
                raise LLMProviderError("Gemini: límite de uso excedido", retriable=True, retry_after=retry) from exc
            if exc.code == 404:
                raise LLMProviderError(f"Gemini: el modelo {request.model!r} no existe o no está disponible") from exc
            raise LLMProviderError(f"Gemini: petición inválida ({exc.code}: {exc.message})") from exc
        except errors.ServerError as exc:
            raise LLMProviderError(f"Gemini: error {exc.code} ({exc.message})", retriable=True) from exc
        except errors.APIError as exc:
            raise LLMProviderError(f"Gemini: error {exc.code} ({exc.message})") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("Gemini: error de conexión", retriable=True) from exc
        return self._to_response(response, request.model)

    def _to_response(self, response: Any, requested_model: str) -> LLMResponse:
        candidates = list(getattr(response, "candidates", None) or [])
        feedback = getattr(response, "prompt_feedback", None)
        blocked = _name(getattr(feedback, "block_reason", None))

        text = ""
        finish: str | None = None
        if candidates:
            candidate = candidates[0]
            finish = _name(getattr(candidate, "finish_reason", None))
            parts = getattr(getattr(candidate, "content", None), "parts", None) or []
            text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))

        if blocked or finish in REFUSAL_REASONS:
            stop_reason = "refusal"
        else:
            stop_reason = _STOP.get(finish or "", (finish or "unknown").lower())

        data: Any | None = None
        if text:
            try:
                data = json.loads(text)
            except ValueError:
                data = None

        usage = getattr(response, "usage_metadata", None)
        prompt = getattr(usage, "prompt_token_count", 0) or 0
        cached = getattr(usage, "cached_content_token_count", 0) or 0
        output = (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
        return LLMResponse(
            data=data,
            raw_text=text,
            model=getattr(response, "model_version", None) or requested_model,
            provider=self.name,
            stop_reason=stop_reason,
            usage=TokenUsage(
                input_tokens=max(prompt - cached, 0), output_tokens=output, cache_read_input_tokens=cached
            ),
        )
