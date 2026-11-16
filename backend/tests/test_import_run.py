"""scripts.import_run: an experiment export becomes a reviewable round of an existing project."""

import json

import pytest

from app.models.platform import RunRecord
from app.pipeline.orchestrator import PipelineSettings, RunReport
from scripts.export_run import export_run
from scripts.import_run import ImportError_, import_run
from tests.conftest import EXAMPLES
from tests.test_platform_api import authorization, create_project, platform  # noqa: F401 (fixture)


def export() -> dict:
    candidates = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((EXAMPLES / "candidates").glob("*.json"))]
    report = RunReport()
    report.finished_at = report.started_at
    return {
        "meta": {"name": "run_001"},
        "settings": PipelineSettings().model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
        "candidates": candidates,
    }


async def test_imported_run_is_reviewed_and_exported(platform):  # noqa: F811
    client, _, _ = platform
    project = await create_project(platform)
    run = await import_run(export(), "Demo")
    assert (run.id, run.project_id, run.round, run.status) == ("run_001", project["id"], 1, "awaiting_review")
    assert run.counts["pending_review"] == 1 and run.counts["discarded"] == 2

    qa = authorization(platform, "qa")
    pending = (await client.get(f"/runs/{run.id}/candidates?status=pending_review", headers=qa)).json()
    assert len(pending) == 1 and pending[0]["project_id"] == project["id"]
    decision = {"decision": "accepted", "review_time_ms": 1234}
    assert (await client.post(f"/candidates/{pending[0]['id']}/decision", headers=qa, json=decision)).status_code == 201

    exported = (await client.get(f"/candidates/export?run_id={run.id}", headers=qa)).json()
    statuses = sorted(c["status"] for c in exported["candidates"])
    assert statuses == ["accepted", "discarded", "discarded"]
    assert {c["run_id"] for c in exported["candidates"]} == {"run_001"}
    assert await export_run(run.id) == exported  # the script writes the same JSON as the endpoint


async def test_import_refuses_duplicates_and_unknown_projects(platform):  # noqa: F811
    await create_project(platform)
    with pytest.raises(ImportError_, match="proyecto"):
        await import_run(export(), "Otro")
    await import_run(export(), "Demo")
    with pytest.raises(ImportError_, match="ya está"):
        await import_run(export(), "Demo")
    assert await RunRecord.find_all().count() == 1
    reviewed = export()
    reviewed["candidates"][-1]["status"] = "accepted"
    reviewed["candidates"] = [c | {"run_id": "run_002"} for c in reviewed["candidates"]]
    with pytest.raises(ImportError_, match="decisiones"):
        await import_run(reviewed, "Demo")
