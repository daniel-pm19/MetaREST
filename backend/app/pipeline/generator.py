"""MR generation: ApiContext → prompt → LLM (structured output) → validated MRSpecs.

Zero-shot (prompt ``gen_v1``). Each generated item is validated on its own: valid
ones become ``MRSpec``; invalid ones are returned in ``rejected`` with the error so
the orchestrator can store them as ``not_executable`` candidates (they count for RQ1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.mr import MRSpec, parse_generated_relations
from app.pipeline.context_extractor import ApiContext
from app.pipeline.llm.base import Effort, LLMProvider, LLMRequest, LLMResponse, TokenUsage
from app.pipeline.prompts import PromptTemplate, neutralize_delimiters
from app.pipeline.wire import from_wire, generation_schema

DEFAULT_PROMPT = "gen_v1"


@dataclass
class GenerationResult:
    specs: list[MRSpec]
    rejected: list[tuple[Any, str]]
    provider: str
    model: str
    prompt_id: str
    usage: TokenUsage
    stop_reason: str | None
    fallback_used: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def _safe_context(context: ApiContext) -> str:
    """Render the spec and neutralize attempts to close the <api_spec> delimiter."""
    return neutralize_delimiters(context.to_prompt_text())


async def generate_relations(
    context: ApiContext,
    provider: LLMProvider,
    *,
    model: str,
    n: int = 20,
    effort: Effort | None = "medium",
    max_tokens: int = 32000,
    template: PromptTemplate | None = None,
) -> GenerationResult:
    if not context.operations:
        raise ValueError("la especificación no tiene operaciones GET/HEAD: no hay nada que probar")
    template = template or PromptTemplate.builtin(DEFAULT_PROMPT)
    prompt = template.render(api_context=_safe_context(context), n=n)
    request = LLMRequest(
        system=prompt.system,
        user=prompt.user,
        json_schema=generation_schema(),
        model=model,
        max_tokens=max_tokens,
        effort=effort,
    )
    response = await provider.complete_json(request)
    return _to_result(response, prompt.prompt_id, n)


def _to_result(response: LLMResponse, prompt_id: str, n: int) -> GenerationResult:
    result = GenerationResult(
        specs=[],
        rejected=[],
        provider=response.provider,
        model=response.model,
        prompt_id=prompt_id,
        usage=response.usage,
        stop_reason=response.stop_reason,
        fallback_used=response.fallback_used,
    )
    if response.refused:
        result.error = "el modelo rechazó la solicitud (stop_reason=refusal)"
        return result
    data = response.data
    if not isinstance(data, dict) or not isinstance(data.get("relations"), list):
        reason = "la salida se truncó por max_tokens" if response.truncated else "la salida no es el JSON esperado"
        result.error = f"{reason}; texto recibido: {response.raw_text[:300]!r}"
        return result
    if response.truncated:
        result.warnings.append("la salida se truncó por max_tokens; se usan las relaciones completas")

    items = data["relations"]
    if len(items) > n:
        result.warnings.append(f"el modelo devolvió {len(items)} relaciones; se conservan las primeras {n}")
        items = items[:n]
    elif len(items) < n:
        result.warnings.append(f"el modelo devolvió {len(items)} relaciones de {n} solicitadas")

    valid, rejected = parse_generated_relations({"relations": [from_wire(item) for item in items]})
    result.specs, result.rejected = valid, rejected
    return result
