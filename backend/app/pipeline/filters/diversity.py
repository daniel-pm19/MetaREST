"""Functional diversity: drop MRs too similar to a better-scored one.

Each MR is embedded through a canonical, language-independent signature of what it
does (endpoints, parameter names, transformations, relation and selectors). Concrete
source values are left out on purpose: the same MR with ``q=jazz`` or ``q=rock`` tests
the same property. Selection is greedy by combined score: an MR whose cosine
similarity to an already selected one is >= threshold becomes ``redundant`` with
``duplicate_of`` pointing to the most similar selected MR.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.mr import (
    AddParam,
    AppendToParam,
    MoveParam,
    MRSpec,
    RemoveParam,
    ScaleParam,
    SetParam,
    Transformation,
)
from app.pipeline.embeddings import Embedder, cosine


def _transformation(t: Transformation) -> str:
    match t:
        case SetParam():
            return f"set_param {t.location.value} {t.param} = {t.value}"
        case AddParam():
            return f"add_param {t.param} = {t.value}"
        case RemoveParam():
            return f"remove_param {t.param}"
        case ScaleParam():
            return f"scale_param {t.location.value} {t.param} x{t.factor:g}"
        case AppendToParam():
            return f"append_to_param {t.param}"
        case MoveParam():
            return f"move_param {t.param} {t.from_location.value} -> {t.to_location.value} {t.to_param or t.param}"
    raise TypeError(f"unknown transformation {t!r}")


def signature(spec: MRSpec) -> str:
    r = spec.relation
    source = spec.source
    params = " ".join(sorted(source.query_params))
    lines = [
        f"relation {r.type.value}" + (f" {r.direction.value}" if r.direction else "") + f" measure {r.measure.value}",
        f"selectors {r.source_selector} {r.effective_followup_selector}",
        f"source {source.method.value} {source.path} query {params}".rstrip(),
    ]
    for i, f in enumerate(spec.followups, 1):
        steps = "; ".join(_transformation(t) for t in f.transformations) or "no transformation"
        lines.append(f"followup {i} {f.method.value} {f.path or source.path}: {steps}")
    return "\n".join(lines)


@dataclass(frozen=True)
class DiversityDecision:
    selected: bool
    max_similarity: float | None  # vs. the MRs selected before it (None for the first one)
    duplicate_of: str | None = None


async def select_diverse(
    items: Sequence[tuple[str, MRSpec, float]], embedder: Embedder, threshold: float
) -> dict[str, DiversityDecision]:
    """``items`` are ``(candidate_id, spec, combined_score)``; returns a decision per id."""
    if not items:
        return {}
    vectors = await embedder.embed([signature(spec) for _, spec, _ in items])
    order = sorted(range(len(items)), key=lambda i: -items[i][2])  # stable: ties keep generation order
    selected: list[int] = []
    decisions: dict[str, DiversityDecision] = {}
    for i in order:
        cid = items[i][0]
        if not selected:
            decisions[cid] = DiversityDecision(selected=True, max_similarity=None)
            selected.append(i)
            continue
        sims = {j: cosine(vectors[i], vectors[j]) for j in selected}
        best = max(sims, key=sims.__getitem__)
        sim = round(max(min(sims[best], 1.0), -1.0), 4)
        if sim >= threshold:
            decisions[cid] = DiversityDecision(selected=False, max_similarity=sim, duplicate_of=items[best][0])
        else:
            decisions[cid] = DiversityDecision(selected=True, max_similarity=sim)
            selected.append(i)
    return decisions
