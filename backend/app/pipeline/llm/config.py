"""LLM settings editable by the Administrator (stored by the backend in `settings`).

API keys are NOT here: they live in backend/.env and are read by each SDK.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.pipeline.llm.base import Effort

ProviderName = Literal["anthropic", "openai", "gemini", "fake"]


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
