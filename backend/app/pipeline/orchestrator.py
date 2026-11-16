"""Pipeline orchestrator: OpenAPI -> context -> generation -> filters -> execution.

``run_pipeline`` returns every candidate of the run (including the discarded ones,
with their reason: they are needed for RQ1/RQ2) plus a ``RunReport`` with the status,
timing, counts and token usage of each stage. It never raises for expected failures
(invalid spec, provider down, refusal...): it sets ``report.error`` and marks the
remaining stages as skipped, so the backend can store the run as failed.

The backend (Nestor) calls it from a background task and persists the result:

    result = await run_pipeline(openapi_text, project_id=..., run_id=..., provider=create_provider(llm),
                                embedder=embedder, sut=SUTClient(base_url), settings=settings,
                                on_progress=save_progress)

``on_progress`` receives a copy of the report every time a stage starts or ends.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.mr import (
    CandidateStatus,
    CriterionScore,
    DiscardReason,
    FilterOutcome,
    MRCandidate,
    MRSpec,
    Provenance,
)
from app.pipeline.context_extractor import ApiContext, SpecError, extract_context
from app.pipeline.embeddings import Embedder
from app.pipeline.executor import SUTClient, execute_many
from app.pipeline.filters import (
    FilterSettings,
    LLMChecker,
    combined_score,
    criterion_score,
    discard_detail,
    fault_violations,
    select_diverse,
    semantic_violations,
)
from app.pipeline.generator import generate_relations
from app.pipeline.llm.base import LLMProvider, LLMProviderError, TokenUsage
from app.pipeline.llm.config import LLMSettings
from app.pipeline.prompts import PromptTemplate

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Expected failure that ends the run (message shown to the user, in Spanish)."""


class StageName(StrEnum):
    EXTRACT = "extract"
    GENERATE = "generate"
    SEMANTIC = "semantic"
    FAULT_REVEALING = "fault_revealing"
    DIVERSITY = "diversity"
    EXECUTE = "execute"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


def _now() -> datetime:
    return datetime.now(UTC)


class StageReport(BaseModel):
    name: StageName
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None
    input_count: int | None = None
    output_count: int | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    detail: str | None = Field(default=None, max_length=1000)


class RunReport(BaseModel):
    stages: list[StageReport] = Field(default_factory=lambda: [StageReport(name=n) for n in StageName])
    provider: str | None = None
    generation_model: str | None = Field(default=None, description="Model that actually answered.")
    verification_model: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    fallback_used: bool = False
    embedder: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None

    def stage(self, name: StageName) -> StageReport:
        return next(s for s in self.stages if s.name is name)

    @property
    def usage(self) -> TokenUsage:
        total = TokenUsage()
        for s in self.stages:
            total = total + s.usage
        return total

    @property
    def ok(self) -> bool:
        return self.error is None


class PipelineSettings(BaseModel):
    """Snapshot of the configuration used by a run (store it with the run)."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    generation_prompt: str = "gen_v1"
    execution_concurrency: int = Field(default=4, ge=1, le=16)


@dataclass
class PipelineResult:
    candidates: list[MRCandidate]
    report: RunReport
    context: ApiContext | None = None

    @property
    def counts(self) -> dict[str, int]:
        """Candidates per status and per discard reason, e.g. {'pending_review': 5, 'redundant': 2}."""
        counts: Counter[str] = Counter(c.status.value for c in self.candidates)
        counts.update(
            c.filter_result.reason.value for c in self.candidates if c.filter_result and c.filter_result.reason
        )
        return dict(counts)


ProgressCallback = Callable[[RunReport], Awaitable[None]]
ScoreFn = Callable[[MRSpec, ApiContext], list[str]]


class _Run:
    def __init__(
        self,
        *,
        project_id: str,
        run_id: str,
        provider: LLMProvider,
        embedder: Embedder | None,
        sut: SUTClient | None,
        settings: PipelineSettings,
        prompts: Mapping[str, PromptTemplate],
        on_progress: ProgressCallback | None,
        new_id: Callable[[], str],
    ):
        self.project_id, self.run_id = project_id, run_id
        self.provider, self.embedder, self.sut = provider, embedder, sut
        self.settings, self.prompts = settings, prompts
        self.on_progress, self.new_id = on_progress, new_id
        self.report = RunReport()
        self.candidates: list[MRCandidate] = []
        self.context: ApiContext | None = None

    # ── helpers ──────────────────────────────────────────────────────────

    async def _progress(self) -> None:
        if self.on_progress is None:
            return
        try:
            await self.on_progress(self.report.model_copy(deep=True))
        except Exception:  # a failing progress write must not kill the run
            logger.exception("progress callback failed for run %s", self.run_id)

    @asynccontextmanager
    async def _stage(self, name: StageName, input_count: int | None = None):
        st = self.report.stage(name)
        st.status, st.started_at, st.input_count = StageStatus.RUNNING, _now(), input_count
        t0 = perf_counter()
        await self._progress()
        try:
            yield st
        except Exception as exc:
            st.status = StageStatus.FAILED
            st.detail = st.detail or str(exc)[:1000]
            raise
        else:
            if st.status is StageStatus.RUNNING:
                st.status = StageStatus.DONE
        finally:
            st.finished_at = _now()
            st.duration_ms = round((perf_counter() - t0) * 1000, 1)
            await self._progress()

    def _template(self, prompt_id: str) -> PromptTemplate:
        if prompt_id in self.prompts:
            return self.prompts[prompt_id]
        try:
            return PromptTemplate.builtin(prompt_id)
        except KeyError as exc:
            raise PipelineError(f"no existe la plantilla de prompt {prompt_id!r}") from exc

    def _alive(self) -> list[MRCandidate]:
        return [c for c in self.candidates if c.spec is not None and c.status is not CandidateStatus.DISCARDED]

    @staticmethod
    def _discard(c: MRCandidate, reason: DiscardReason, detail: str, duplicate_of: str | None = None) -> None:
        c.filter_result = FilterOutcome(passed=False, reason=reason, detail=detail[:1000], duplicate_of=duplicate_of)
        c.status = CandidateStatus.DISCARDED

    # ── stages ───────────────────────────────────────────────────────────

    async def extract(self, spec: str | bytes | dict[str, Any] | ApiContext) -> ApiContext:
        async with self._stage(StageName.EXTRACT) as st:
            ctx = spec if isinstance(spec, ApiContext) else extract_context(spec)
            if not ctx.operations:
                raise PipelineError("la especificación no tiene operaciones GET/HEAD: no hay nada que probar")
            st.output_count = len(ctx.operations)
            st.detail = f"{len(ctx.operations)} operaciones GET/HEAD; {ctx.skipped_operations} no seguras omitidas"
        self.context = ctx
        return ctx

    async def generate(self, ctx: ApiContext) -> None:
        llm = self.settings.llm
        async with self._stage(StageName.GENERATE) as st:
            result = await generate_relations(
                ctx,
                self.provider,
                model=llm.generation_model,
                n=llm.max_candidates,
                effort=llm.generation_effort,
                max_tokens=llm.generation_max_tokens,
                template=self._template(self.settings.generation_prompt),
            )
            st.usage = result.usage
            self.report.provider, self.report.generation_model = result.provider, result.model
            self.report.fallback_used = result.fallback_used
            self.report.prompt_versions["generation"] = result.prompt_id
            self.report.warnings.extend(result.warnings)
            if result.error:
                raise PipelineError(f"la generación falló: {result.error}")

            provenance = Provenance(provider=result.provider, model=result.model, prompt_version=result.prompt_id)
            for spec in result.specs:
                self.candidates.append(self._candidate(provenance, spec=spec))
            for item, error in result.rejected:
                outcome = FilterOutcome(passed=False, reason=DiscardReason.NOT_EXECUTABLE, detail=error[:1000])
                self.candidates.append(
                    self._candidate(
                        provenance, raw_output=item, filter_result=outcome, status=CandidateStatus.DISCARDED
                    )
                )
            st.output_count = len(result.specs)
            st.detail = f"{len(result.specs)} válidas, {len(result.rejected)} no ejecutables"

    def _candidate(self, provenance: Provenance, **fields: Any) -> MRCandidate:
        return MRCandidate(
            id=self.new_id(), project_id=self.project_id, run_id=self.run_id, provenance=provenance, **fields
        )

    def _checker(self, prompt_id: str) -> LLMChecker | None:
        llm, filters = self.settings.llm, self.settings.filters
        if not filters.use_llm_checks:
            return None
        self.report.verification_model = llm.verification_model
        return LLMChecker(
            self.provider,
            self._template(prompt_id),
            model=llm.verification_model,
            effort=llm.verification_effort,
            max_tokens=llm.verification_max_tokens,
            concurrency=filters.llm_concurrency,
        )

    async def _criterion(
        self, ctx: ApiContext, stage: StageName, rules: ScoreFn, prompt_id: str, threshold: float, reason: DiscardReason
    ) -> list[tuple[MRCandidate, CriterionScore]]:
        alive = self._alive()
        async with self._stage(stage, len(alive)) as st:
            checker = self._checker(prompt_id)
            if checker:
                self.report.prompt_versions[stage.value] = checker.prompt_id

            async def score(c: MRCandidate) -> tuple[CriterionScore, TokenUsage, bool]:
                assert c.spec is not None
                violations = rules(c.spec, ctx)
                check = await checker.check(c.spec, ctx) if checker and not violations else None
                failed = check is not None and check.error is not None
                return criterion_score(violations, check), check.usage if check else TokenUsage(), failed

            results = await asyncio.gather(*(score(c) for c in alive))
            scored: list[tuple[MRCandidate, CriterionScore]] = []
            failures = 0
            for c, (crit, usage, failed) in zip(alive, results, strict=True):
                st.usage = st.usage + usage
                failures += failed
                scored.append((c, crit))
                if not crit.rules_passed or crit.score < threshold:
                    self._discard(c, reason, discard_detail(crit, threshold))
            if failures:
                self.report.warnings.append(
                    f"{failures} chequeos LLM de la etapa {stage.value} fallaron; se usaron solo las reglas"
                )
            st.output_count = len(self._alive())
            st.detail = f"{len(alive) - st.output_count} descartadas"
        return scored

    async def semantic(self, ctx: ApiContext) -> None:
        f = self.settings.filters
        for c, crit in await self._criterion(
            ctx,
            StageName.SEMANTIC,
            semantic_violations,
            f.semantic_prompt,
            f.min_semantic,
            DiscardReason.INVALID_SEMANTICS,
        ):
            c.scores.semantic_validity = crit

    async def fault_revealing(self, ctx: ApiContext) -> None:
        f = self.settings.filters
        for c, crit in await self._criterion(
            ctx,
            StageName.FAULT_REVEALING,
            fault_violations,
            f.fault_prompt,
            f.min_fault_revealing,
            DiscardReason.LOW_FAULT_REVEALING,
        ):
            c.scores.fault_revealing = crit
        for c in self._alive():
            sem, fault = c.scores.semantic_validity, c.scores.fault_revealing
            assert sem is not None and fault is not None
            c.scores.combined = combined_score(sem.score, fault.score, f)

    async def diversity(self) -> None:
        alive = self._alive()
        async with self._stage(StageName.DIVERSITY, len(alive)) as st:
            if self.embedder is None:
                st.status, st.detail = StageStatus.SKIPPED, "sin modelo de embeddings: no se filtró por diversidad"
                self.report.warnings.append(st.detail)
            else:
                self.report.embedder = self.embedder.name
                threshold = self.settings.filters.similarity_threshold
                items = [(c.id, c.spec, c.scores.combined or 0.0) for c in alive if c.spec is not None]
                decisions = await select_diverse(items, self.embedder, threshold)
                for c in alive:
                    d = decisions[c.id]
                    c.scores.max_similarity = d.max_similarity
                    if not d.selected:
                        detail = f"similitud {d.max_similarity:.2f} con {d.duplicate_of} (umbral {threshold:g})"
                        self._discard(c, DiscardReason.REDUNDANT, detail, duplicate_of=d.duplicate_of)
                st.detail = f"{len(alive) - len(self._alive())} redundantes"
            survivors = self._alive()
            for c in survivors:
                c.filter_result = FilterOutcome(passed=True)
                c.status = CandidateStatus.PENDING_REVIEW
            st.output_count = len(survivors)

    async def execute(self) -> None:
        survivors = self._alive()
        async with self._stage(StageName.EXECUTE, len(survivors)) as st:
            if self.sut is None:
                st.status, st.detail = StageStatus.SKIPPED, "sin SUT configurada: las MRs no se ejecutaron"
                return
            specs = [c.spec for c in survivors if c.spec is not None]
            results = await execute_many(specs, self.sut, concurrency=self.settings.execution_concurrency)
            for c, r in zip(survivors, results, strict=True):
                c.execution = r
            verdicts = Counter(r.verdict.value for r in results)
            st.output_count = len(results)
            st.detail = ", ".join(f"{k}: {v}" for k, v in sorted(verdicts.items())) or "nada que ejecutar"

    # ── entry point ──────────────────────────────────────────────────────

    async def run(self, spec: str | bytes | dict[str, Any] | ApiContext) -> PipelineResult:
        try:
            ctx = await self.extract(spec)
            await self.generate(ctx)
            await self.semantic(ctx)
            await self.fault_revealing(ctx)
            await self.diversity()
            await self.execute()
        except (PipelineError, SpecError, LLMProviderError) as exc:
            self.report.error = str(exc)[:1000]
        except Exception as exc:
            logger.exception("pipeline run %s failed", self.run_id)
            self.report.error = f"error interno: {type(exc).__name__}: {exc}"[:1000]
        for st in self.report.stages:
            if st.status is StageStatus.PENDING:
                st.status = StageStatus.SKIPPED
        self.report.finished_at = _now()
        await self._progress()
        # Re-validate: assignments above bypass the model validators (contract invariants).
        candidates = [MRCandidate.model_validate(c.model_dump()) for c in self.candidates]
        return PipelineResult(candidates=candidates, report=self.report, context=self.context)


async def run_pipeline(
    spec: str | bytes | dict[str, Any] | ApiContext,
    *,
    project_id: str,
    run_id: str,
    provider: LLMProvider,
    embedder: Embedder | None,
    sut: SUTClient | None,
    settings: PipelineSettings | None = None,
    prompts: Mapping[str, PromptTemplate] | None = None,
    on_progress: ProgressCallback | None = None,
    new_id: Callable[[], str] = lambda: uuid4().hex,
) -> PipelineResult:
    """Run the whole pipeline once. ``prompts`` overrides built-in templates by id (Admin edits)."""
    run = _Run(
        project_id=project_id,
        run_id=run_id,
        provider=provider,
        embedder=embedder,
        sut=sut,
        settings=settings or PipelineSettings(),
        prompts=prompts or {},
        on_progress=on_progress,
        new_id=new_id,
    )
    return await run.run(spec)
