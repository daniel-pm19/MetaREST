"""Loading run exports and manual MRs; writing CSVs."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.mr import CandidateStatus, DiscardReason, MRCandidate, MRSpec


@dataclass
class RunData:
    """One pipeline run as exported by ``smoke_pipeline`` or the backend: settings + report + candidates."""

    path: Path
    settings: dict[str, Any]
    report: dict[str, Any]
    candidates: list[MRCandidate]

    @property
    def run_id(self) -> str:
        if self.candidates:
            return self.candidates[0].run_id
        return self.path.stem

    @property
    def label(self) -> str:
        """File name without extension: unique per export even when two runs share a run_id."""
        return self.path.stem

    @property
    def similarity_threshold(self) -> float | None:
        return (self.settings.get("filters") or {}).get("similarity_threshold")


@dataclass(frozen=True)
class NamedMR:
    """An MR to execute, from any technique (MetaREST candidate or manual baseline)."""

    id: str
    title: str
    spec: MRSpec
    technique: str
    status: str = ""  # candidate status / "manual"
    filter_reason: str = ""  # discard reason, "" when it passed
    extra: dict[str, Any] = field(default_factory=dict, compare=False)


def load_run(path: Path) -> RunData:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):  # a bare candidate export
        data = {"candidates": data}
    candidates = [MRCandidate.model_validate(c) for c in data.get("candidates", [])]
    return RunData(
        path=path, settings=data.get("settings") or {}, report=data.get("report") or {}, candidates=candidates
    )


def load_runs(paths: Iterable[Path]) -> list[RunData]:
    return [load_run(p) for p in paths]


Selection = str  # "accepted" | "passed" | "all"


def select_candidates(runs: Sequence[RunData], select: Selection = "passed") -> list[NamedMR]:
    """MetaREST MRs to execute.

    * ``accepted``: accepted by the QA Auditor (what the paper calls MetaREST's output).
    * ``passed``: survived the automatic filter (accepted, rejected or pending review).
    * ``all``: every executable candidate, discarded ones included (RQ2: did a redundant MR detect more?).
    """
    out: list[NamedMR] = []
    for run in runs:
        for c in run.candidates:
            if c.spec is None:
                continue
            passed = c.filter_result is None or c.filter_result.passed
            if select == "accepted" and c.status is not CandidateStatus.ACCEPTED:
                continue
            if select == "passed" and not passed:
                continue
            reason = "" if passed or c.filter_result is None else c.filter_result.reason.value
            out.append(
                NamedMR(
                    id=c.id,
                    title=c.spec.title,
                    spec=c.spec,
                    technique="metarest",
                    status=c.status.value,
                    filter_reason=reason,
                    extra={
                        "run_id": c.run_id,
                        "duplicate_of": c.filter_result.duplicate_of if c.filter_result else None,
                    },
                )
            )
    return out


def load_manual_mrs(directory: Path) -> list[NamedMR]:
    """Manual baseline MRs: ``*.json`` files with one MRSpec or a list of them (same schema as the pipeline).

    The id is the file stem (plus ``#n`` for lists). A file that does not validate stops the run: a broken
    baseline MR must be fixed, not silently skipped.
    """
    out: list[NamedMR] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        for i, item in enumerate(items):
            if isinstance(item, dict) and "spec" in item and "title" not in item:  # an MRCandidate-like wrapper
                item = item["spec"]
            try:
                spec = MRSpec.model_validate(item)
            except ValueError as exc:
                raise ValueError(f"{path.name}[{i}]: MR manual inválida: {exc}") from exc
            mr_id = path.stem if len(items) == 1 else f"{path.stem}#{i + 1}"
            out.append(NamedMR(id=mr_id, title=spec.title, spec=spec, technique="manual", status="manual"))
    return out


def write_csv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(columns or (rows[0].keys() if rows else []))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _cell(row.get(k)) for k in cols})
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:  # -sig: sheets re-saved by Excel/LibreOffice
        return list(csv.DictReader(fh))


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def discard_reason(c: MRCandidate) -> DiscardReason | None:
    if c.filter_result is None or c.filter_result.passed:
        return None
    return c.filter_result.reason
