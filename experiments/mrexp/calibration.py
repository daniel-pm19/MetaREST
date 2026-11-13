"""Calibration of the LLM checks (verification model, effort, thresholds) before the experiments.

Ground truth comes from execution against the real API, not from the LLM:

* **valid**: a real generated MR that passes the rules and *passes* on the real API;
* **invalid**: a mutant of a real MR (relation swapped or direction flipped, text rewritten to match) that
  passes the rules and *violates* on the real API.

Anything else (an original that violates, a mutant that still passes) is ``uncertain`` and left out of the metrics.
The calibration set comes from the smoke runs, never from the experiment runs, so RQ1 is not tuned on its own data.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.mr import Direction, MRSpec, RelationType
from app.pipeline.context_extractor import ApiContext
from app.pipeline.executor import SUTClient, execute_many
from app.pipeline.filters import fault_violations, semantic_violations
from app.pipeline.filters.llm_check import LLMChecker
from app.pipeline.llm.base import Effort, LLMProvider
from app.pipeline.prompts import PromptTemplate

from mrexp.io import RunData

SPECS = Path(__file__).resolve().parents[1] / "specs"


@dataclass(frozen=True)
class SUTPreset:
    spec: Path
    base_url: str
    max_concurrency: int = 4
    min_interval: float = 0.0
    timeout: float = 10.0

    def client(self) -> SUTClient:
        return SUTClient(
            self.base_url, max_concurrency=self.max_concurrency, min_interval=self.min_interval, timeout=self.timeout
        )


PRESETS = {  # same settings as experiments/specs/README.md
    "pokeapi": SUTPreset(SPECS / "pokeapi.yaml", "https://pokeapi.co"),
    "crossref": SUTPreset(SPECS / "crossref.json", "https://api.crossref.org", 1, 1.0, 30.0),
}

# ───────────────────────────── mutants ─────────────────────────────

_FLIP = {
    Direction.FOLLOWUP_IN_SOURCE: Direction.SOURCE_IN_FOLLOWUP,
    Direction.SOURCE_IN_FOLLOWUP: Direction.FOLLOWUP_IN_SOURCE,
}
# Collection relations -> one that contradicts it whenever the selections share elements.
_SWAP = {
    RelationType.EQUALITY: RelationType.DISJOINT,
    RelationType.EQUIVALENCE: RelationType.DISJOINT,
    RelationType.COMPLETE: RelationType.DISJOINT,
    RelationType.SAME_ORDER: RelationType.DISJOINT,
    RelationType.DIFFERENCE: RelationType.EQUALITY,
    RelationType.DISJOINT: RelationType.EQUALITY,
}
_CLAIM = {
    RelationType.DISJOINT: "Los elementos seleccionados de la fuente y de los follow-ups no comparten ningún elemento.",
    RelationType.EQUALITY: "Lo seleccionado en la fuente y en cada follow-up es idéntico y en el mismo orden.",
    RelationType.SUBSET: "Los elementos seleccionados de un lado están contenidos en los del otro, según la dirección.",
    RelationType.COUNT_LEQ: "La medida seleccionada de un lado es menor o igual que la del otro, según la dirección.",
}


def mutate(spec: MRSpec) -> tuple[str, MRSpec] | None:
    """One plausible-looking but wrong variant of ``spec``, or None if no operator applies.

    The text fields are rewritten to state the new relation, so the check cannot spot the mutant just because
    the description contradicts the relation (an invalid LLM-generated MR is usually self-consistent).
    """
    r = spec.relation
    if r.type in (RelationType.SUBSET, RelationType.COUNT_LEQ) and r.direction in _FLIP:
        operator, relation = "flip_direction", r.model_copy(update={"direction": _FLIP[r.direction]})
    elif r.type in _SWAP:
        new = _SWAP[r.type]
        operator, relation = f"{r.type.value}_to_{new.value}", r.model_copy(update={"type": new, "direction": None})
    else:
        return None
    claim = _CLAIM[relation.type]
    data = spec.model_dump(mode="json")
    data.update(
        relation=relation.model_dump(mode="json"),
        title=f"{spec.title[:100]} (variante)",
        description=claim,
        expected_relation=claim,
    )
    try:
        return operator, MRSpec.model_validate(data)
    except ValueError:  # e.g. difference needs exactly 2 follow-ups and equality accepts them, but be safe
        return None


@dataclass
class CalibrationItem:
    case: str
    id: str
    kind: str  # original | mutant
    operator: str
    spec: MRSpec
    rule_violations: list[str] = field(default_factory=list)
    verdict: str = ""
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)  # config -> {sem, fault, reasons, errors}

    @property
    def label(self) -> str:
        if self.rule_violations:
            return "rules"
        if self.kind == "original" and self.verdict == "pass":
            return "valid"
        if self.kind == "mutant" and self.verdict == "violation":
            return "invalid"
        return "uncertain"


def build_items(case: str, run: RunData, ctx: ApiContext) -> list[CalibrationItem]:
    items: list[CalibrationItem] = []
    for c in run.candidates:
        if c.spec is None:
            continue
        items.append(CalibrationItem(case, c.id[:8], "original", "", c.spec))
        mutant = mutate(c.spec)
        if mutant:
            items.append(CalibrationItem(case, c.id[:8] + "-m", "mutant", mutant[0], mutant[1]))
    for item in items:
        item.rule_violations = semantic_violations(item.spec, ctx) + fault_violations(item.spec, ctx)
    return items


async def execute_items(items: Sequence[CalibrationItem], client: SUTClient, concurrency: int) -> None:
    todo = [i for i in items if not i.rule_violations]
    results = await execute_many([i.spec for i in todo], client, concurrency=concurrency)
    for item, result in zip(todo, results, strict=True):
        item.verdict = result.verdict.value


# ───────────────────────────── checks ─────────────────────────────


@dataclass(frozen=True)
class CheckConfig:
    model: str
    effort: Effort | None
    prompts: str = "v1"  # semcheck_<v> / faultcheck_<v>

    @property
    def name(self) -> str:
        return f"{self.model}:{self.effort or 'none'}:{self.prompts}"

    @classmethod
    def parse(cls, text: str) -> CheckConfig:
        """``model[:effort[:prompt version]]``, e.g. ``gemini-3.5-flash-lite:low:v2``; effort ``none`` = no thinking."""
        model, effort, prompts = (text.split(":") + ["", ""])[:3]
        effort = effort or "low"
        return cls(model, None if effort == "none" else effort, prompts or "v1")  # type: ignore[arg-type]


async def run_checks(
    items: Sequence[CalibrationItem],
    contexts: dict[str, ApiContext],
    provider: LLMProvider,
    config: CheckConfig,
    *,
    concurrency: int = 4,
) -> None:
    sem = asyncio.Semaphore(concurrency)
    checkers = {
        name: LLMChecker(provider, PromptTemplate.builtin(pid), model=config.model, effort=config.effort, semaphore=sem)
        for name, pid in (("sem", f"semcheck_{config.prompts}"), ("fault", f"faultcheck_{config.prompts}"))
    }

    async def one(item: CalibrationItem) -> None:
        sem_check, fault_check = await asyncio.gather(
            *(checkers[k].check(item.spec, contexts[item.case]) for k in ("sem", "fault"))
        )
        item.checks[config.name] = {
            "sem": sem_check.score,
            "fault": fault_check.score,
            "sem_reason": sem_check.reason,
            "fault_reason": fault_check.reason,
            "errors": [e for e in (sem_check.error, fault_check.error) if e],
            "tokens": sem_check.usage.total + fault_check.usage.total,
        }

    await asyncio.gather(*(one(i) for i in items if not i.rule_violations))


# ───────────────────────────── metrics ─────────────────────────────

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)


def auc(valid: Sequence[float], invalid: Sequence[float]) -> float | None:
    """P(score of a random valid MR > score of a random invalid one); ties count 1/2."""
    if not valid or not invalid:
        return None
    wins = sum(1.0 if v > i else 0.5 if v == i else 0.0 for v in valid for i in invalid)
    return wins / (len(valid) * len(invalid))


def summary_rows(items: Sequence[CalibrationItem], configs: Sequence[str]) -> list[dict[str, Any]]:
    rows = []
    for name in configs:
        scored = [i for i in items if name in i.checks and i.checks[name]["sem"] is not None]
        valid = [i.checks[name]["sem"] for i in scored if i.label == "valid"]
        invalid = [i.checks[name]["sem"] for i in scored if i.label == "invalid"]
        fault_valid = [i.checks[name]["fault"] for i in scored if i.label == "valid" and i.checks[name]["fault"]]
        row: dict[str, Any] = {
            "config": name,
            "valid": len(valid),
            "invalid": len(invalid),
            "errors": sum(1 for i in items if name in i.checks and i.checks[name]["errors"]),
            "tokens": sum(i.checks[name]["tokens"] for i in items if name in i.checks),
            "sem_mean_valid": sum(valid) / len(valid) if valid else None,
            "sem_mean_invalid": sum(invalid) / len(invalid) if invalid else None,
            "sem_auc": auc(valid, invalid),
            "fault_mean_valid": sum(fault_valid) / len(fault_valid) if fault_valid else None,
        }
        for t in THRESHOLDS:
            row[f"keep_valid@{t}"] = sum(v >= t for v in valid) / len(valid) if valid else None
            row[f"drop_invalid@{t}"] = sum(v < t for v in invalid) / len(invalid) if invalid else None
        rows.append(row)
    return rows


def item_rows(items: Sequence[CalibrationItem], configs: Sequence[str]) -> list[dict[str, Any]]:
    rows = []
    for i in items:
        row: dict[str, Any] = {
            "case": i.case,
            "id": i.id,
            "kind": i.kind,
            "operator": i.operator,
            "relation": i.spec.relation.type.value,
            "title": i.spec.title,
            "verdict": i.verdict,
            "label": i.label,
            "rule_violations": i.rule_violations,
        }
        for name in configs:
            check = i.checks.get(name, {})
            row[f"sem[{name}]"] = check.get("sem")
            row[f"fault[{name}]"] = check.get("fault")
            row[f"sem_reason[{name}]"] = check.get("sem_reason")
        rows.append(row)
    return rows
