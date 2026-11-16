"""LLM settings editable by the Administrator (stored by the backend in `settings`).

API keys are NOT here: they live in backend/.env and are read by each SDK.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.pipeline.llm.base import Effort

ProviderName = Literal["anthropic", "openai", "gemini", "fake"]

# Default (generation, verification) models per provider; used when the models are not set explicitly.
DEFAULT_MODELS: dict[str, tuple[str, str]] = {
    "anthropic": ("claude-sonnet-5-5", "claude-haiku-5-5"),
    "gemini": ("gemini-4-hydrogen", "gemini-3.5-flash-lite"),
}
# Client-side request rate per model when not set explicitly. Gemini's free tier allows 15 requests/min on
# Flash-Lite (measured 13-nov-2026); going over it makes checks fail.
DEFAULT_RPM: dict[str, int] = {"gemini": 12}
# Verification effort per provider when not set explicitly. Gemini Flash-Lite with "low" missed 2 of 13 invalid
# MRs in the calibration; "medium" missed none (docs/LLM.md D15). Claude keeps "low" (D4, not calibrated).
DEFAULT_VERIFICATION_EFFORT: dict[str, Effort] = {"gemini": "medium"}


class LLMSettings(BaseModel):
    provider: ProviderName = "anthropic"
    generation_model: str = "claude-sonnet-5-5"
    generation_effort: Effort = "medium"
    generation_max_tokens: int = Field(default=32000, ge=1024, le=128000)
    verification_model: str = "claude-haiku-5-5"
    verification_effort: Effort = "low"
    verification_max_tokens: int = Field(default=4000, ge=256, le=128000)
    max_candidates: int = Field(default=20, ge=1, le=50, description="MRs requested per run (cost control).")
    enable_fallbacks: bool = Field(default=True, description="Server-side refusal fallbacks when supported.")
    timeout_seconds: float = Field(default=600.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    requests_per_minute: int | None = Field(
        default=None, ge=1, le=10000, description="Client-side limit per model; None = no limit."
    )

    @model_validator(mode="after")
    def _provider_models(self) -> LLMSettings:
        generation, verification = DEFAULT_MODELS.get(self.provider, (self.generation_model, self.verification_model))
        if "generation_model" not in self.model_fields_set:
            self.generation_model = generation
        if "verification_model" not in self.model_fields_set:
            self.verification_model = verification
        if "verification_effort" not in self.model_fields_set:
            self.verification_effort = DEFAULT_VERIFICATION_EFFORT.get(self.provider, self.verification_effort)
        if "requests_per_minute" not in self.model_fields_set:
            self.requests_per_minute = DEFAULT_RPM.get(self.provider)
        return self
