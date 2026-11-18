"""Platform integration with the team's pipeline; no duplicated inference/executor."""

import asyncio
import logging
from collections import Counter

from app.models.mr import CandidateStatus
from app.models.platform import ApiContextRecord, CandidateRecord, DecisionRecord, RunRecord, now
from app.pipeline.embeddings import FastEmbedEmbedder
from app.pipeline.executor import SUTClient
from app.pipeline.llm import create_provider
from app.pipeline.orchestrator import StageStatus, run_pipeline
from app.pipeline.prompts import PromptTemplate
from app.sut_auth import SUTAuthError, project_headers

logger = logging.getLogger(__name__)


async def candidates_for_run(run_id: str):
    records = await CandidateRecord.find(CandidateRecord.candidate.run_id == run_id).to_list()
    decisions = {d.candidate_id: d for d in await DecisionRecord.find(DecisionRecord.run_id == run_id).to_list()}
    values = []
    for record in records:
        candidate = record.candidate.model_copy(deep=True)
        if candidate.id in decisions:
            candidate.status = CandidateStatus(decisions[candidate.id].decision)
        values.append(candidate)
    return values


async def execute_run(app, run_id: str):
    run = await RunRecord.get(run_id)
    project = run.project_snapshot
    try:

        async def save_progress(report):
            await RunRecord.find_one(RunRecord.id == run_id).update(
                {"$set": {"report": report.model_dump(mode="json")}}
            )

        headers = project_headers(project.get("auth_env_key"))
        model = run.settings.filters.embedding_model
        if model not in app.state.embedders:
            app.state.embedders[model] = FastEmbedEmbedder(model, cache_dir=app.state.settings.fastembed_cache_dir)
        prompts = {
            key: PromptTemplate.from_strings(key, value["system"], value["user"])
            for key, value in run.prompts_snapshot.items()
        }
        async with SUTClient(
            project["base_url"],
            headers=headers,
            max_concurrency=project["max_concurrency"],
            min_interval=project["min_interval"],
            timeout=project["timeout"],
        ) as sut:
            result = await run_pipeline(
                project["openapi"],
                project_id=run.project_id,
                run_id=run.id,
                provider=create_provider(run.settings.llm),
                embedder=app.state.embedders[model],
                sut=sut,
                settings=run.settings,
                prompts=prompts,
                on_progress=save_progress,
            )
        if result.candidates:
            await CandidateRecord.insert_many([CandidateRecord(id=c.id, candidate=c) for c in result.candidates])
        if result.context is not None:
            await ApiContextRecord(
                project_id=run.project_id,
                run_id=run.id,
                context=result.context.model_dump(mode="json"),
            ).insert()
        await RunRecord.find_one(RunRecord.id == run.id).update(
            {
                "$set": {
                    "report": result.report.model_dump(mode="json"),
                    "counts": result.counts,
                    "status": "awaiting_review" if result.report.ok else "failed",
                }
            }
        )
    except asyncio.CancelledError:
        await fail_run(run_id, "Ejecución interrumpida al detener el servidor")
        raise
    except SUTAuthError as exc:
        await fail_run(run_id, str(exc))
    except Exception:
        # SDK/network exceptions can contain secrets: keep them out of the API/report.
        logger.error("Run %s failed outside the pipeline", run_id)
        await fail_run(run_id, "Error de integración del pipeline; revisa la configuración del servidor")


async def fail_run(run_id: str, message: str):
    run = await RunRecord.get(run_id)
    if run is None:
        return
    report = run.report
    report.error = message
    report.finished_at = now()
    for stage in report.stages:
        if stage.status == StageStatus.RUNNING:
            stage.status = StageStatus.FAILED
            stage.finished_at = report.finished_at
        elif stage.status == StageStatus.PENDING:
            stage.status = StageStatus.SKIPPED
    await RunRecord.find_one(RunRecord.id == run_id).update(
        {
            "$set": {
                "status": "failed",
                "report": report.model_dump(mode="json"),
            }
        }
    )


async def metrics(run: RunRecord) -> dict:
    candidates = await candidates_for_run(run.id)
    counts = Counter(c.status.value for c in candidates)
    kept = [c for c in candidates if c.status != CandidateStatus.DISCARDED]
    decisions = await DecisionRecord.find(DecisionRecord.run_id == run.id).to_list()
    times = [d.review_time_ms for d in decisions if d.review_time_ms is not None]
    decided = counts["accepted"] + counts["rejected"]
    return {
        "run_id": run.id,
        "round": run.round,
        "generated": len(candidates),
        "discarded": counts["discarded"],
        "pending": counts["pending_review"],
        "accepted": counts["accepted"],
        "rejected": counts["rejected"],
        "violations": sum(bool(c.execution and c.execution.verdict.value == "violation") for c in kept),
        # Frontend compatibility: accepted violations, not independently confirmed SUT defects.
        "confirmed_faults": sum(
            bool(c.status == CandidateStatus.ACCEPTED and c.execution and c.execution.verdict.value == "violation")
            for c in kept
        ),
        "acceptance_rate": counts["accepted"] / decided if decided else None,
        "tokens": run.report.usage.total,
        "avg_combined": round(100 * sum(c.scores.combined or 0 for c in kept) / len(kept)) if kept else 0,
        "avg_review_ms": round(sum(times) / len(times)) if times else None,
    }
