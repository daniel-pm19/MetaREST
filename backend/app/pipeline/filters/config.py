"""Filter settings editable by the Administrator (stored by the backend in `settings`)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class FilterSettings(BaseModel):
    # Weights of the combined score (normalized, so they only need a positive sum).
    semantic_weight: float = Field(default=0.5, ge=0)
    fault_weight: float = Field(default=0.5, ge=0)
    # Minimum score per criterion; below it the MR is discarded at that stage.
    min_semantic: float = Field(default=0.6, ge=0, le=1)
    min_fault_revealing: float = Field(default=0.5, ge=0, le=1)
    # Cosine similarity at or above which an MR is redundant with a higher-scored one. Calibrated with
    # bge-small on MR signatures: distinct MRs 0.83-0.93, same MR with other values 0.98-0.999 (docs/LLM.md).
    similarity_threshold: float = Field(default=0.975, gt=0, le=1)
    # LLM checks (verification model from LLMSettings). Off = rules only (score 1.0 when rules pass).
    use_llm_checks: bool = True
    llm_concurrency: int = Field(default=4, ge=1, le=16)
    semantic_prompt: str = "semcheck_v1"
    fault_prompt: str = "faultcheck_v1"
    # Local embedding model (fastembed / ONNX).
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    @model_validator(mode="after")
    def _weights(self) -> FilterSettings:
        if self.semantic_weight + self.fault_weight <= 0:
            raise ValueError("at least one weight must be positive")
        return self
