"""LLM verification shared by the semantic and fault-revealing filters.

One short call per MR and criterion (verification model, e.g. Claude Haiku 5.5),
returning ``{"score": 0..1, "reason": "..."}`` validated with Pydantic. The API
description and the MR are both untrusted (the MR was written by another LLM call
that read the spec), so both go delimited and with their delimiters neutralized.
SUT responses are never included.

A failed check (provider error, refusal, invalid output) does not stop the run: it is
reported in ``LLMCheck.error`` and the scorer falls back to the rules-only score.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.models.mr import MRSpec
from app.pipeline.context_extractor import ApiContext
from app.pipeline.executor.http import build_url
from app.pipeline.llm.base import Effort, LLMProvider, LLMProviderError, LLMRequest, TokenUsage
from app.pipeline.prompts import PromptTemplate, neutralize_delimiters

CHECK_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}


class CheckOutput(BaseModel):
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()[:1000]


@dataclass
class LLMCheck:
    score: float | None = None
    reason: str | None = None
    error: str | None = None
    model: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)


def _operations_text(spec: MRSpec, ctx: ApiContext) -> str:
    """Only the operations the MR touches: keeps the check short and cheap."""
    source, followups = spec.instances()[0]
    wanted = {(r.method.value, r.path) for r in (source, *followups)}
    ops = [op for op in ctx.operations if (op.method.value, op.path) in wanted]
    return neutralize_delimiters(ctx.model_copy(update={"operations": ops}).to_prompt_text())


def _mr_text(spec: MRSpec) -> str:
    body = json.dumps(spec.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2)
    lines = [body, "", "Concrete requests:"]
    for i, (source, followups) in enumerate(spec.instances()):
        label = "base instance" if i == 0 else f"input variant {i}"
        lines.append(f"- {label}: source {source.method.value} {build_url('', source)}")
        lines.extend(f"  follow-up {j}: {f.method.value} {build_url('', f)}" for j, f in enumerate(followups, 1))
    return neutralize_delimiters("\n".join(lines))


class LLMChecker:
    """Runs one criterion's check with bounded concurrency."""

    def __init__(
        self,
        provider: LLMProvider,
        template: PromptTemplate,
        *,
        model: str,
        effort: Effort | None = "low",
        max_tokens: int = 4000,
        concurrency: int = 4,
        semaphore: asyncio.Semaphore | None = None,
    ):
        self.provider = provider
        self.template = template
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._sem = semaphore or asyncio.Semaphore(concurrency)

    @property
    def prompt_id(self) -> str:
        return self.template.prompt_id

    async def check(self, spec: MRSpec, ctx: ApiContext) -> LLMCheck:
        prompt = self.template.render(api_context=_operations_text(spec, ctx), mr=_mr_text(spec))
        request = LLMRequest(
            system=prompt.system,
            user=prompt.user,
            json_schema=CHECK_SCHEMA,
            model=self.model,
            max_tokens=self.max_tokens,
            effort=self.effort,
        )
        async with self._sem:
            try:
                response = await self.provider.complete_json(request)
            except LLMProviderError as exc:
                return LLMCheck(error=f"error del proveedor: {exc}")
        result = LLMCheck(model=response.model, usage=response.usage)
        if response.refused:
            result.error = "el modelo rechazó la verificación"
            return result
        try:
            out = CheckOutput.model_validate(response.data)
        except ValidationError as exc:
            result.error = f"salida inválida: {exc.errors(include_url=False)[0]['msg']}"
            return result
        result.score, result.reason = out.score, out.reason
        return result
