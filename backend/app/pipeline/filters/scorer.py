"""Scores per criterion and combined score.

* Rules broken -> score 0 (the LLM is not even asked).
* Rules pass + LLM score -> the LLM score.
* Rules pass + no LLM score (checks disabled or failed) -> 1.0, i.e. rules only.
"""

from __future__ import annotations

from app.models.mr import CriterionScore
from app.pipeline.filters.config import FilterSettings
from app.pipeline.filters.llm_check import LLMCheck


def criterion_score(violations: list[str], check: LLMCheck | None) -> CriterionScore:
    if violations:
        return CriterionScore(rules_passed=False, rule_violations=violations, score=0.0)
    if check is None:
        return CriterionScore(rules_passed=True, score=1.0)
    if check.score is None:
        reason = f"chequeo LLM no disponible ({check.error}); se usa solo el resultado de las reglas"
        return CriterionScore(rules_passed=True, llm_reason=reason[:1000], score=1.0)
    return CriterionScore(rules_passed=True, llm_score=check.score, llm_reason=check.reason, score=check.score)


def combined_score(semantic: float, fault: float, settings: FilterSettings) -> float:
    total = settings.semantic_weight + settings.fault_weight
    value = (settings.semantic_weight * semantic + settings.fault_weight * fault) / total
    return round(min(max(value, 0.0), 1.0), 4)


def discard_detail(score: CriterionScore, threshold: float) -> str:
    if not score.rules_passed:
        return "; ".join(score.rule_violations)[:1000]
    detail = f"puntuación {score.score:.2f} por debajo del umbral {threshold:.2f}"
    if score.llm_reason:
        detail += f": {score.llm_reason}"
    return detail[:1000]
