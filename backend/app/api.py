"""HTTP platform endpoints matching the existing frontend client."""

import csv
import io
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from jinja2 import Environment, TemplateSyntaxError
from pymongo.errors import DuplicateKeyError

from app.auth import Admin, Reader, Writer, hash_password, issue_token, verify_password
from app.models.mr import CandidateStatus, MRCandidate
from app.models.platform import (
    AuditRecord,
    CandidateRecord,
    DecisionRecord,
    ProjectRecord,
    PromptRecord,
    RunRecord,
    SettingsRecord,
    UserRecord,
)
from app.pipeline.context_extractor import SpecError, extract_context
from app.pipeline.filters import FilterSettings
from app.pipeline.llm.config import LLMSettings
from app.pipeline.orchestrator import PipelineSettings
from app.pipeline.prompts import PromptTemplate, available_prompts
from app.schemas import (
    DecisionInput,
    LoginInput,
    LoginOutput,
    MetricsOutput,
    NewProject,
    NewPrompt,
    NewUser,
    ProjectOutput,
    PromptOutput,
    RunOutput,
    UserOutput,
    UserPatch,
)
from app.services import candidates_for_run, execute_run, metrics

router = APIRouter()


async def get_or_404(model, record_id: str):
    record = await model.get(record_id)
    if record is None:
        raise HTTPException(404, "Recurso no encontrado")
    return record


def user_view(user: UserRecord) -> dict:
    return {key: getattr(user, key) for key in ("id", "name", "email", "role", "active")}


def project_view(project: ProjectRecord) -> dict:
    return {key: getattr(project, key) for key in ("id", "name", "base_url", "endpoints", "created_at")}


async def run_view(run: RunRecord) -> dict:
    candidates = await candidates_for_run(run.id)
    counts = Counter(c.status.value for c in candidates)
    counts.update(c.filter_result.reason.value for c in candidates if c.filter_result and c.filter_result.reason)
    return {
        "id": run.id,
        "project_id": run.project_id,
        "project_name": run.project_name,
        "round": run.round,
        "status": run.status,
        "report": run.report.model_dump(mode="json"),
        "counts": dict(counts),
    }


async def audit(user: UserRecord, action: str, resource_id: str):
    await AuditRecord(user_id=user.id, action=action, resource_id=resource_id).insert()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/login", response_model=LoginOutput, tags=["auth"])
async def login(body: LoginInput, request: Request):
    user = await UserRecord.find_one(UserRecord.email == str(body.email).lower())
    # Fixed dummy work for unknown users reduces the email enumeration timing difference.
    hashed = user.password_hash if user else request.app.state.dummy_password_hash
    valid = await run_in_threadpool(verify_password, body.password, hashed)
    if not user or not valid or not user.active:
        raise HTTPException(401, "Correo o contraseña incorrectos", headers={"WWW-Authenticate": "Bearer"})
    return {
        "access_token": issue_token(user, request.app.state.settings),
        "token_type": "bearer",
        "user": user_view(user),
    }


@router.get("/auth/me", response_model=UserOutput, tags=["auth"])
async def me(user: Reader):
    return user_view(user)


@router.get("/users", response_model=list[UserOutput], tags=["users"])
async def users(user: Admin):
    return [user_view(u) for u in await UserRecord.find_all().to_list()]


@router.post("/users", response_model=UserOutput, status_code=201, tags=["users"])
async def create_user(body: NewUser, user: Admin):
    record = UserRecord(
        name=body.name,
        email=str(body.email).lower(),
        role=body.role,
        password_hash=await run_in_threadpool(hash_password, body.password),
    )
    try:
        await record.insert()
    except DuplicateKeyError:
        raise HTTPException(409, "Ya existe un usuario con ese correo") from None
    await audit(user, "user.created", record.id)
    return user_view(record)


@router.patch("/users/{user_id}", response_model=UserOutput, tags=["users"])
async def update_user(user_id: str, body: UserPatch, user: Admin):
    if user_id == user.id:
        raise HTTPException(400, "No puedes cambiar tu propio rol ni desactivarte")
    record = await get_or_404(UserRecord, user_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    await record.replace()
    await audit(user, "user.updated", record.id)
    return user_view(record)


@router.delete("/users/{user_id}", status_code=204, tags=["users"])
async def delete_user(user_id: str, user: Admin):
    # Soft deletion preserves decision authors and their audit history.
    await update_user(user_id, UserPatch(active=False), user)


@router.get("/projects", response_model=list[ProjectOutput], tags=["projects"])
async def projects(user: Reader):
    return [project_view(p) for p in await ProjectRecord.find_all().sort("created_at").to_list()]


async def validated_project(body: NewProject, request: Request):
    if len(body.openapi.encode("utf-8")) > request.app.state.settings.max_spec_bytes:
        raise HTTPException(413, "OpenAPI demasiado grande")
    try:
        context = extract_context(body.openapi)
    except SpecError:
        raise HTTPException(422, "Especificación OpenAPI inválida") from None
    if not context.operations:
        raise HTTPException(422, "OpenAPI no contiene operaciones GET/HEAD")
    return context


@router.post("/projects", response_model=ProjectOutput, status_code=201, tags=["projects"])
async def create_project(body: NewProject, request: Request, user: Writer):
    context = await validated_project(body, request)
    record = ProjectRecord(**body.model_dump(), endpoints=len(context.operations))
    await record.insert()
    await audit(user, "project.created", record.id)
    return project_view(record)


@router.get("/projects/{project_id}", response_model=ProjectOutput, tags=["projects"])
async def project(project_id: str, user: Reader):
    return project_view(await get_or_404(ProjectRecord, project_id))


@router.put("/projects/{project_id}", response_model=ProjectOutput, tags=["projects"])
async def update_project(project_id: str, body: NewProject, request: Request, user: Writer):
    record = await get_or_404(ProjectRecord, project_id)
    context = await validated_project(body, request)
    for key, value in body.model_dump().items():
        setattr(record, key, value)
    record.endpoints = len(context.operations)
    await record.replace()
    await audit(user, "project.updated", record.id)
    return project_view(record)


@router.get("/projects/{project_id}/runs", response_model=list[RunOutput], tags=["runs"])
async def runs(project_id: str, user: Reader):
    await get_or_404(ProjectRecord, project_id)
    return [await run_view(r) for r in await RunRecord.find(RunRecord.project_id == project_id).sort("round").to_list()]


@router.post("/projects/{project_id}/runs", response_model=RunOutput, status_code=202, tags=["runs"])
async def start_run(project_id: str, request: Request, tasks: BackgroundTasks, user: Writer):
    project = await get_or_404(ProjectRecord, project_id)
    settings = await SettingsRecord.get("pipeline")
    prompts = await PromptRecord.find_all().to_list()
    last = await RunRecord.find(RunRecord.project_id == project_id).sort("-round").first_or_none()
    record = RunRecord(
        project_id=project.id,
        project_name=project.name,
        round=last.round + 1 if last else 1,
        settings=settings.pipeline.model_copy(deep=True),
        project_snapshot=project.model_dump(exclude={"id", "created_at", "revision_id"}),
        prompts_snapshot={p.id: {"system": p.system, "user": p.user} for p in prompts},
    )
    try:
        await record.insert()
    except DuplicateKeyError:
        raise HTTPException(409, "Ya existe una iteración en curso; vuelve a consultar el proyecto") from None
    await audit(user, "run.started", record.id)
    tasks.add_task(execute_run, request.app, record.id)
    return await run_view(record)


@router.get("/runs/{run_id}", response_model=RunOutput, tags=["runs"])
async def run(run_id: str, user: Reader):
    return await run_view(await get_or_404(RunRecord, run_id))


@router.get("/runs/{run_id}/candidates", response_model=list[MRCandidate], tags=["candidates"])
async def candidates(run_id: str, user: Reader, status: CandidateStatus | None = None):
    await get_or_404(RunRecord, run_id)
    values = await candidates_for_run(run_id)
    return [c for c in values if status is None or c.status == status]


@router.post("/candidates/{candidate_id}/decision", status_code=201, tags=["decisions"])
async def decide(candidate_id: str, body: DecisionInput, user: Writer):
    record = await get_or_404(CandidateRecord, candidate_id)
    candidate = record.candidate
    if candidate.status != CandidateStatus.PENDING_REVIEW:
        raise HTTPException(409, "Solo se pueden decidir candidatas pendientes")
    decision = DecisionRecord(
        candidate_id=candidate.id,
        run_id=candidate.run_id,
        user_id=user.id,
        user=user.name,
        title=candidate.spec.title if candidate.spec else candidate.id,
        provenance=candidate.provenance,
        **body.model_dump(),
    )
    try:
        # This unique append is authoritative. Concurrent decisions cannot overwrite it.
        await decision.insert()
    except DuplicateKeyError:
        raise HTTPException(409, "La candidata ya tiene una decisión") from None
    await CandidateRecord.find_one(CandidateRecord.id == candidate_id).update(
        {
            "$set": {"candidate.status": body.decision},
        }
    )
    return {"id": decision.id, "candidate_id": candidate_id, "decision": decision.decision}


@router.get("/audit", tags=["decisions"])
async def decisions(user: Reader, run_id: str | None = None):
    query = DecisionRecord.find(DecisionRecord.run_id == run_id) if run_id else DecisionRecord.find_all()
    return [
        {
            "id": d.id,
            "candidate_id": d.candidate_id,
            "run_id": d.run_id,
            "title": d.title,
            "decision": d.decision,
            "justification": d.justification,
            "review_time_ms": d.review_time_ms,
            "user": d.user,
            "at": d.created_at.isoformat(),
            "provenance": d.provenance.model_dump(mode="json"),
        }
        for d in await query.sort("-created_at").to_list()
    ]


@router.get("/candidates/export", tags=["export"])
async def export_candidates(run_id: str, user: Writer, format: str = Query(default="json", pattern="^(json|csv)$")):
    run = await get_or_404(RunRecord, run_id)
    values = await candidates_for_run(run_id)
    if format == "json":
        return {
            "settings": run.settings.model_dump(mode="json"),
            "report": run.report.model_dump(mode="json"),
            "candidates": [c.model_dump(mode="json") for c in values],
        }
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "run_id", "status", "title", "discard_reason", "verdict", "combined"])
    for candidate in values:
        title = candidate.spec.title if candidate.spec else ""
        if title.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
            title = "'" + title
        writer.writerow(
            [
                candidate.id,
                candidate.run_id,
                candidate.status.value,
                title,
                candidate.filter_result.reason.value
                if candidate.filter_result and candidate.filter_result.reason
                else "",
                candidate.execution.verdict.value if candidate.execution else "",
                candidate.scores.combined,
            ]
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="candidates.csv"'},
    )


@router.get("/metrics/compare", response_model=list[MetricsOutput], tags=["metrics"])
async def compare_runs(user: Reader, runs: str = Query(max_length=2000)):
    ids = list(dict.fromkeys(runs.split(",")))
    if not 1 <= len(ids) <= 20 or any(not value for value in ids):
        raise HTTPException(422, "Indica entre 1 y 20 ids de iteración")
    return [await metrics(await get_or_404(RunRecord, record_id)) for record_id in ids]


@router.get("/metrics/project/{project_id}", response_model=list[MetricsOutput], tags=["metrics"])
async def project_metrics(project_id: str, user: Reader):
    await get_or_404(ProjectRecord, project_id)
    return [await metrics(r) for r in await RunRecord.find(RunRecord.project_id == project_id).sort("round").to_list()]


@router.get("/settings/llm", response_model=LLMSettings, tags=["settings"])
async def llm_settings(user: Admin):
    return (await SettingsRecord.get("pipeline")).pipeline.llm


def validate_provider_models(settings: LLMSettings) -> None:
    for model in (settings.generation_model, settings.verification_model):
        name = model.removeprefix("models/")
        if (settings.provider == "gemini" and name.startswith("claude-")) or (
            settings.provider == "anthropic" and name.startswith("gemini-")
        ):
            raise HTTPException(422, "Los modelos no corresponden al proveedor; actualiza ambos modelos al cambiarlo")


@router.put("/settings/llm", response_model=LLMSettings, tags=["settings"])
async def save_llm(body: LLMSettings, user: Admin):
    if body.provider not in {"anthropic", "gemini"}:
        raise HTTPException(422, "Solo Anthropic y Gemini están habilitados para ejecuciones reales")
    validate_provider_models(body)
    record = await SettingsRecord.get("pipeline")
    record.pipeline.llm = body
    await record.replace()
    await audit(user, "settings.llm", record.id)
    return body


@router.get("/settings/thresholds", response_model=FilterSettings, tags=["settings"])
async def filter_settings(user: Admin):
    return (await SettingsRecord.get("pipeline")).pipeline.filters


@router.put("/settings/thresholds", response_model=FilterSettings, tags=["settings"])
async def save_filters(body: FilterSettings, user: Admin):
    settings = await SettingsRecord.get("pipeline")
    for name in (body.semantic_prompt, body.fault_prompt):
        if name not in available_prompts() and await PromptRecord.get(name) is None:
            raise HTTPException(422, f"Prompt no encontrado: {name}")
    settings.pipeline.filters = body
    await settings.replace()
    await audit(user, "settings.thresholds", settings.id)
    return body


@router.get("/prompts", response_model=list[PromptOutput], tags=["prompts"])
async def prompts(user: Admin):
    rows = []
    for prompt_id in available_prompts():
        template = PromptTemplate.builtin(prompt_id)
        kind = (
            "generation"
            if prompt_id.startswith("gen_")
            else "semantic"
            if prompt_id.startswith("semcheck_")
            else "fault"
        )
        rows.append(
            {
                "id": prompt_id,
                "kind": kind,
                "system": template.system_source,
                "user": template.user_source,
                "editable": False,
            }
        )
    rows.extend(
        {"id": p.id, "kind": p.kind, "system": p.system, "user": p.user, "editable": True}
        for p in await PromptRecord.find_all().to_list()
    )
    return rows


@router.post("/prompts", response_model=PromptOutput, status_code=201, tags=["prompts"])
async def create_prompt(body: NewPrompt, user: Admin):
    if body.id in available_prompts():
        raise HTTPException(409, "Los prompts del repositorio son inmutables; crea una versión con otro id")
    try:
        Environment().parse(body.system)
        Environment().parse(body.user)
    except TemplateSyntaxError:
        raise HTTPException(422, "Sintaxis de plantilla Jinja inválida") from None
    try:
        await PromptRecord(**body.model_dump()).insert()
    except DuplicateKeyError:
        raise HTTPException(409, "Ya existe un prompt con ese id") from None
    await audit(user, "prompt.created", body.id)
    return {**body.model_dump(), "editable": True}


@router.put("/prompts/{prompt_id}", tags=["prompts"])
async def replace_prompt(prompt_id: str, body: NewPrompt, user: Admin):
    # Provenance stores prompt IDs: edits are new immutable versions, never overwrites.
    raise HTTPException(409, "Crea una nueva versión con POST /prompts para preservar la trazabilidad")


@router.delete("/prompts/{prompt_id}", status_code=204, tags=["prompts"])
async def delete_prompt(prompt_id: str, user: Admin):
    record = await get_or_404(PromptRecord, prompt_id)
    settings = (await SettingsRecord.get("pipeline")).pipeline
    used = [settings.generation_prompt, settings.filters.semantic_prompt, settings.filters.fault_prompt]
    if prompt_id in used or await RunRecord.find_one({f"prompts_snapshot.{prompt_id}": {"$exists": True}}):
        raise HTTPException(409, "No se puede borrar un prompt configurado o usado por una iteración")
    await record.delete()
    await audit(user, "prompt.deleted", prompt_id)


@router.get("/settings/pipeline", response_model=PipelineSettings, tags=["settings"])
async def pipeline_settings(user: Admin):
    return (await SettingsRecord.get("pipeline")).pipeline


@router.put("/settings/pipeline", response_model=PipelineSettings, tags=["settings"])
async def save_pipeline_settings(body: PipelineSettings, user: Admin):
    if body.llm.provider not in {"anthropic", "gemini"}:
        raise HTTPException(422, "Proveedor no habilitado")
    validate_provider_models(body.llm)
    for prompt_id in (body.generation_prompt, body.filters.semantic_prompt, body.filters.fault_prompt):
        if prompt_id not in available_prompts() and await PromptRecord.get(prompt_id) is None:
            raise HTTPException(422, "Prompt no encontrado")
    record = await SettingsRecord.get("pipeline")
    record.pipeline = body
    await record.replace()
    await audit(user, "settings.pipeline", record.id)
    return body
