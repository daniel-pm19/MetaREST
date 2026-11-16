"""Load an experiment run export into the platform, so the QA Auditor reviews its candidates in the UI.

The export is the JSON written by ``python -m mrexp run`` (or ``scripts.smoke_pipeline``): ``{meta?, settings,
report, candidates}``. It becomes a new round of an **existing** project (create the project in the UI first, with
the same OpenAPI). Candidates keep their ids and ``run_id``, so after the review ``GET /candidates/export`` returns
the same keys the experiment results use, and ``mrexp mutants --select accepted`` can run on it.

Nothing is regenerated or re-executed: no LLM calls, no requests to the SUT.

With the Docker Compose stack (Mongo is not published to the host), from the repository root:

    docker compose --env-file backend/.env -f infra/docker-compose.yml exec -T backend \\
      python -m scripts.import_run --project "API demo" < experiments/raw/demo_run1.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from typing import Any

from app.models.mr import MRCandidate
from app.models.platform import CandidateRecord, ProjectRecord, RunRecord
from app.pipeline.orchestrator import PipelineSettings, RunReport


class ImportError_(RuntimeError):  # noqa: N801 (avoid shadowing the builtin ImportError)
    pass


def _counts(candidates: list[MRCandidate]) -> dict[str, int]:
    counts: Counter[str] = Counter(c.status.value for c in candidates)
    counts.update(c.filter_result.reason.value for c in candidates if c.filter_result and c.filter_result.reason)
    return dict(counts)


async def import_run(payload: dict[str, Any], project_name: str) -> RunRecord:
    """Insert the export as a new round of the project named ``project_name``; return the new run."""
    projects = await ProjectRecord.find(ProjectRecord.name == project_name).to_list()
    if len(projects) != 1:
        raise ImportError_(f"se esperaba 1 proyecto llamado {project_name!r}, hay {len(projects)}")
    project = projects[0]
    candidates = [MRCandidate.model_validate(c) for c in payload.get("candidates", [])]
    run_ids = {c.run_id for c in candidates}
    if len(run_ids) != 1:
        raise ImportError_(f"el export debe tener candidatas de un solo run, tiene {sorted(run_ids)}")
    (run_id,) = run_ids
    if await RunRecord.get(run_id) is not None:
        raise ImportError_(f"el run {run_id!r} ya está en la plataforma")
    if any(c.status.value in ("accepted", "rejected") for c in candidates):
        raise ImportError_("el export ya tiene decisiones; se importa solo un run sin revisar")

    candidates = [c.model_copy(update={"project_id": project.id}) for c in candidates]
    last = await RunRecord.find(RunRecord.project_id == project.id).sort("-round").first_or_none()
    report = RunReport.model_validate(payload["report"])
    run = RunRecord(
        id=run_id,
        project_id=project.id,
        project_name=project.name,
        round=last.round + 1 if last else 1,
        status="awaiting_review" if report.ok else "failed",
        report=report,
        settings=PipelineSettings.model_validate(payload["settings"]),
        counts=_counts(candidates),
        project_snapshot=project.model_dump(exclude={"id", "created_at", "revision_id"}),
    )
    await run.insert()
    if candidates:
        await CandidateRecord.insert_many([CandidateRecord(id=c.id, candidate=c) for c in candidates])
    return run


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="name of an existing project (as shown in the UI)")
    parser.add_argument("export", nargs="?", help="export JSON file (default: read from stdin)")
    args = parser.parse_args()
    payload = json.loads(open(args.export, encoding="utf-8").read() if args.export else sys.stdin.read())

    from app.config import Settings
    from app.db import initialize_database

    client = await initialize_database(Settings())
    try:
        run = await import_run(payload, args.project)
    except ImportError_ as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        client.close()
    print(f"run {run.id} importado como iteración {run.round} de {run.project_name!r}: {run.counts}")


if __name__ == "__main__":
    asyncio.run(main())
