"""MetaREST runs for the experiments, with the frozen settings of ``config/experiment.json``.

Same pipeline the backend calls (``run_pipeline``), so a run here is equivalent to one launched from the UI.
The export has the format the backend's ``GET /candidates/export`` must produce (docs/INTEGRATION.md), plus a
``meta`` block for the paper's reproducibility section (commit, spec hash, config hash).

A run is **usable** for RQ1–RQ3 only if it ended without error and every LLM check answered: a failed check falls
back to the rules (score 1.0, docs/LLM.md D11), which would inflate the filter's results.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.pipeline.embeddings import Embedder
from app.pipeline.executor import SUTClient
from app.pipeline.llm.base import LLMProvider
from app.pipeline.orchestrator import (
    PipelineResult,
    PipelineSettings,
    ProgressCallback,
    run_pipeline,
)

from mrexp.suts import SUTPreset

ROOT = Path(__file__).resolve().parents[1]
FROZEN_CONFIG = ROOT / "config" / "experiment.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_settings(path: Path) -> PipelineSettings:
    return PipelineSettings.model_validate_json(path.read_text(encoding="utf-8"))


def git_info(repo: Path = ROOT.parent) -> dict[str, Any]:
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--", "backend/app", "experiments/config"))
    return {"commit": commit or None, "pipeline_dirty": dirty if commit else None}


def problems(result: PipelineResult) -> list[str]:
    """Why the run must not be used for the experiments (empty = usable)."""
    out = [f"error: {result.report.error}"] if result.report.error else []
    out += [w for w in result.report.warnings if "chequeo" in w.lower()]
    return out


async def execute_run(
    name: str,
    sut_name: str,
    preset: SUTPreset,
    settings: PipelineSettings,
    provider: LLMProvider,
    embedder: Embedder | None,
    *,
    client: SUTClient | None = None,
    config_path: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[PipelineResult, dict[str, Any]]:
    """Run the pipeline once against ``preset``; return the result and the export payload."""
    spec_bytes = preset.spec.read_bytes()
    started = datetime.now(UTC)
    async with client or preset.client() as sut:
        result = await run_pipeline(
            spec_bytes.decode("utf-8"),
            project_id=sut_name,
            run_id=name,
            provider=provider,
            embedder=embedder,
            sut=sut,
            settings=settings,
            on_progress=on_progress,
        )
    meta = {
        "name": name,
        "sut": sut_name,
        "base_url": preset.base_url,
        "spec_file": preset.spec.name,
        "spec_sha256": sha256(spec_bytes),
        "config_file": config_path.name if config_path else None,
        "config_sha256": sha256(config_path.read_bytes()) if config_path else None,
        "sut_client": {
            "max_concurrency": preset.max_concurrency,
            "min_interval": preset.min_interval,
            "timeout": preset.timeout,
        },
        "started_at": started.isoformat(),
        "git": git_info(),
        "usable": not problems(result),
        "problems": problems(result),
    }
    payload = {
        "meta": meta,
        "settings": settings.model_dump(mode="json"),
        "report": result.report.model_dump(mode="json"),
        "candidates": [c.model_dump(mode="json") for c in result.candidates],
    }
    return result, payload


def write_export(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
