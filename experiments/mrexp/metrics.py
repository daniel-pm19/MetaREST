"""RQ1 (validity before/after the filter), RQ2 (redundancy before/after diversity) and coverage."""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.models.mr import DiscardReason, MRCandidate, MRSpec, RequestSpec
from app.pipeline.context_extractor import ApiContext
from app.pipeline.embeddings import Embedder, cosine
from app.pipeline.executor import build_url
from app.pipeline.filters.diversity import signature

from mrexp.io import RunData, discard_reason

# ───────────────────────────── RQ1 ──────────────────────────────

LABEL_COLUMNS = ["label_a", "label_b", "label_final", "notes"]
TRUE_LABELS = {"1", "si", "sí", "s", "yes", "y", "v", "valida", "válida", "valid", "true"}
FALSE_LABELS = {"0", "no", "n", "i", "invalida", "inválida", "invalid", "false"}


def key(c: MRCandidate) -> str:
    return f"{c.run_id}/{c.id}"


def _req(r: RequestSpec) -> str:
    return f"{r.method.value} {build_url('', r)}"


def label_sheet_rows(runs: Sequence[RunData], *, seed: int = 13) -> list[dict[str, Any]]:
    """Every candidate (discarded ones included) for manual validity labeling.

    The sheet is **blind**: no filter decision, score or execution verdict (only surviving MRs are executed,
    so a verdict would reveal the filter). Rows are shuffled with a fixed seed so labelers do not see the
    generation order. Candidates that were not executable get ``0`` pre-filled (editable) with a note.
    """
    rows: list[dict[str, Any]] = []
    for run in runs:
        for c in run.candidates:
            row: dict[str, Any] = {"key": key(c), **dict.fromkeys(LABEL_COLUMNS, "")}
            if c.spec is None:
                raw = c.raw_output if isinstance(c.raw_output, dict) else {}
                row.update(
                    title=str(raw.get("title", "")),
                    description=str(raw.get("description", "")),
                    raw_output=raw or c.raw_output,
                    label_a="0",
                    label_b="0",
                    notes="no ejecutable: no cumple el esquema (prellenado, se puede cambiar)",
                )
            else:
                row.update(_spec_columns(c.spec))
            rows.append(row)
    random.Random(seed).shuffle(rows)
    return rows


SHEET_COLUMNS = [
    "key",
    "title",
    "description",
    "operation",
    "source_requests",
    "followup_requests",
    "relation",
    "source_selector",
    "followup_selector",
    "transformation_logic",
    "expected_relation",
    "rationale",
    "raw_output",
    *LABEL_COLUMNS,
]


def _spec_columns(spec: MRSpec) -> dict[str, Any]:
    instances = spec.instances()
    r = spec.relation
    relation = r.type.value + (f" ({r.direction.value})" if r.direction else "")
    if r.type.value == "count_leq":
        relation += f" measure={r.measure.value}"
    return {
        "title": spec.title,
        "description": spec.description,
        "operation": f"{spec.source.method.value} {spec.source.path}",
        "source_requests": " | ".join(_req(src) for src, _ in instances),
        "followup_requests": " | ".join(" ; ".join(_req(f) for f in fus) for _, fus in instances),
        "relation": relation,
        "source_selector": r.source_selector,
        "followup_selector": r.effective_followup_selector,
        "transformation_logic": spec.transformation_logic,
        "expected_relation": spec.expected_relation,
        "rationale": spec.rationale,
    }


def parse_label(value: str | None, where: str = "") -> bool | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in TRUE_LABELS:
        return True
    if text in FALSE_LABELS:
        return False
    raise ValueError(f"{where}: etiqueta no reconocida {value!r} (usa 1/0, sí/no)")


def cohen_kappa(pairs: Sequence[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa for two raters and a binary label. None without pairs."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa = sum(a for a, _ in pairs) / n
    pb = sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe == 1:  # both raters used a single, identical label: perfect but degenerate agreement
        return 1.0
    return (po - pe) / (1 - pe)


@dataclass
class Labeled:
    candidate: MRCandidate
    a: bool | None
    b: bool | None
    final: bool | None  # label_final if given, else a when a == b, else None (disagreement)

    @property
    def passed(self) -> bool:
        return self.candidate.filter_result is None or self.candidate.filter_result.passed


def join_labels(runs: Sequence[RunData], sheet: Sequence[dict[str, str]]) -> list[Labeled]:
    by_key = {row["key"]: row for row in sheet}
    out = []
    for run in runs:
        for c in run.candidates:
            row = by_key.get(key(c), {})
            k = key(c)
            a = parse_label(row.get("label_a"), f"{k} label_a")
            b = parse_label(row.get("label_b"), f"{k} label_b")
            final = parse_label(row.get("label_final"), f"{k} label_final")
            if final is None and a is not None and a == b:
                final = a
            out.append(Labeled(c, a, b, final))
    return out


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def rq1_rows(labeled: Sequence[Labeled], group: str = "all") -> dict[str, Any]:
    """Validity before/after the filter, per labeler and agreed, plus the filter's confusion matrix."""
    pre = [x for x in labeled if x.final is not None]
    post = [x for x in pre if x.passed]
    pairs = [(x.a, x.b) for x in labeled if x.a is not None and x.b is not None]
    kept_valid = sum(1 for x in pre if x.passed and x.final)
    kept_invalid = sum(1 for x in pre if x.passed and not x.final)
    dropped_valid = sum(1 for x in pre if not x.passed and x.final)
    dropped_invalid = sum(1 for x in pre if not x.passed and not x.final)
    row: dict[str, Any] = {
        "group": group,
        "candidates": len(labeled),
        "labeled": len(pre),
        "disagreements_unresolved": sum(1 for x in labeled if x.a is not None and x.b is not None and x.final is None),
        "unlabeled": sum(1 for x in labeled if x.a is None or x.b is None),
        "kappa": cohen_kappa(pairs),
        "raw_agreement": _rate(sum(a == b for a, b in pairs), len(pairs)),
        "n_pre": len(pre),
        "valid_pre": sum(x.final for x in pre),
        "valid_rate_pre": _rate(sum(x.final for x in pre), len(pre)),
        "n_post": len(post),
        "valid_post": sum(x.final for x in post),
        "valid_rate_post": _rate(sum(x.final for x in post), len(post)),
        "kept_valid": kept_valid,
        "kept_invalid": kept_invalid,
        "discarded_valid": dropped_valid,
        "discarded_invalid": dropped_invalid,
        "filter_precision": _rate(kept_valid, kept_valid + kept_invalid),
        "filter_recall_valid": _rate(kept_valid, kept_valid + dropped_valid),
        "invalid_removed_rate": _rate(dropped_invalid, dropped_invalid + kept_invalid),
    }
    for who in ("a", "b"):
        own_pre = [getattr(x, who) for x in labeled if getattr(x, who) is not None]
        own_post = [getattr(x, who) for x in labeled if getattr(x, who) is not None and x.passed]
        row[f"valid_rate_pre_{who}"] = _rate(sum(own_pre), len(own_pre))
        row[f"valid_rate_post_{who}"] = _rate(sum(own_post), len(own_post))
    return row


def rq1_by_stage_rows(labeled: Sequence[Labeled]) -> list[dict[str, Any]]:
    """Where the filter discarded MRs and how many of those the labelers considered valid (false discards)."""
    stages: dict[str, list[Labeled]] = {}
    for x in labeled:
        reason = discard_reason(x.candidate)
        stages.setdefault(reason.value if reason else "passed", []).append(x)
    order = ["passed", *(r.value for r in DiscardReason)]
    return [
        {
            "outcome": name,
            "candidates": len(stages[name]),
            "labeled_valid": sum(1 for x in stages[name] if x.final is True),
            "labeled_invalid": sum(1 for x in stages[name] if x.final is False),
            "not_agreed": sum(1 for x in stages[name] if x.final is None),
        }
        for name in order
        if name in stages
    ]


# ───────────────────────────── RQ2 ──────────────────────────────


def _components(n: int, edges: Iterable[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in edges:
        parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def redundancy(ids: Sequence[str], vectors: Sequence[Sequence[float]], threshold: float) -> dict[str, Any]:
    """Clusters = connected components of the graph "cosine >= threshold" (same signature as the filter)."""
    n = len(ids)
    sims = {(i, j): cosine(vectors[i], vectors[j]) for i in range(n) for j in range(i + 1, n)}
    edges = [pair for pair, s in sims.items() if s >= threshold]
    clusters = _components(n, edges)
    max_sim = [max((s for (i, j), s in sims.items() if k in (i, j)), default=None) for k in range(n)]
    known = [s for s in max_sim if s is not None]
    return {
        "mrs": n,
        "clusters": len(clusters),
        "redundant_mrs": n - len(clusters),
        "redundancy_rate": _rate(n - len(clusters), n),
        "redundant_pairs": len(edges),
        "mean_max_similarity": sum(known) / len(known) if known else None,
        "cluster_members": [[ids[i] for i in c] for c in clusters if len(c) > 1],
    }


def _reached_diversity(c: MRCandidate) -> bool:
    reason = discard_reason(c)
    return c.spec is not None and reason in (None, DiscardReason.REDUNDANT)


async def rq2_rows(
    runs: Sequence[RunData], embedder: Embedder, thresholds: Sequence[float] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per run and threshold: redundancy of generated / pre-diversity / post-diversity sets, and the clusters.

    ``thresholds`` defaults to the threshold the run used (``filters.similarity_threshold``).
    """
    summary: list[dict[str, Any]] = []
    clusters: list[dict[str, Any]] = []
    for run in runs:
        executable = [c for c in run.candidates if c.spec is not None]
        vectors = dict(
            zip((c.id for c in executable), await embedder.embed([signature(c.spec) for c in executable]), strict=True)
        )
        sets = {
            "generated": executable,
            "pre_diversity": [c for c in executable if _reached_diversity(c)],
            "post_diversity": [c for c in executable if discard_reason(c) is None],
        }
        used = run.similarity_threshold or 0.975
        for threshold in thresholds or [used]:
            for name, members in sets.items():
                stats = redundancy([c.id for c in members], [vectors[c.id] for c in members], threshold)
                groups = stats.pop("cluster_members")
                summary.append({"run": run.label, "threshold": threshold, "run_threshold": used, "set": name, **stats})
                for n, group in enumerate(groups, 1):
                    clusters.append(
                        {"run": run.label, "threshold": threshold, "set": name, "cluster": n, "members": group}
                    )
    return summary, clusters


def redundant_unique_detection_rows(detections: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
    """From a ``mutants --select all`` detections CSV: faults detected by MRs discarded as redundant
    that no selected (passed) MetaREST MR detects."""
    selected: dict[str, set[str]] = {}
    redundant: dict[str, set[str]] = {}
    faults: list[str] = []
    for row in detections:
        if row["technique"] != "metarest" or row["variant"] == "original":
            continue
        fault = row["variant"]
        if fault not in faults:
            faults.append(fault)
        if str(row["detected"]) not in ("1", "True", "true"):
            continue
        if row["filter_reason"] == "":
            selected.setdefault(fault, set()).add(row["item_id"])
        elif row["filter_reason"] == DiscardReason.REDUNDANT.value:
            redundant.setdefault(fault, set()).add(row["item_id"])
    return [
        {
            "fault": f,
            "detected_by_selected": len(selected.get(f, ())),
            "detected_by_redundant": len(redundant.get(f, ())),
            "redundant_items": sorted(redundant.get(f, ())),
            "only_redundant_detect": bool(redundant.get(f)) and not selected.get(f),
        }
        for f in faults
    ]


# ─────────────────────────── coverage ────────────────────────────


def coverage_rows(
    context: ApiContext, groups: dict[str, Sequence[MRSpec]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Operations and (operation, parameter) pairs of the spec exercised by each group's concrete requests.

    Only documented parameters count; requests to paths that are not in the spec are reported apart.
    """
    ops = {(op.method.value, op.path): op for op in context.operations}
    all_params = {(m, p, prm.location, prm.name) for (m, p), op in ops.items() for prm in op.parameters}
    summary, uncovered = [], []
    for group, specs in groups.items():
        hit_ops: set[tuple[str, str]] = set()
        hit_params: set[tuple[str, str, str, str]] = set()
        unknown: set[str] = set()
        for spec in specs:
            for src, fus in spec.instances():
                for req in (src, *fus):
                    op_key = (req.method.value, req.path)
                    if op_key not in ops:
                        unknown.add(f"{req.method.value} {req.path}")
                        continue
                    hit_ops.add(op_key)
                    names = [("query", n) for n in req.query_params] + [("path", n) for n in req.path_params]
                    hit_params.update((*op_key, loc, n) for loc, n in names if (*op_key, loc, n) in all_params)
        summary.append(
            {
                "group": group,
                "mrs": len(specs),
                "ops_covered": len(hit_ops),
                "ops_total": len(ops),
                "ops_rate": _rate(len(hit_ops), len(ops)),
                "params_covered": len(hit_params),
                "params_total": len(all_params),
                "params_rate": _rate(len(hit_params), len(all_params)),
                "requests_outside_spec": sorted(unknown),
            }
        )
        for m, p in sorted(set(ops) - hit_ops):
            uncovered.append({"group": group, "kind": "operation", "method": m, "path": p, "param": ""})
        for m, p, loc, n in sorted(all_params - hit_params):
            if (m, p) in hit_ops:  # params of uncovered operations are implied by the operation row
                uncovered.append({"group": group, "kind": "param", "method": m, "path": p, "param": f"{loc}:{n}"})
    return summary, uncovered
