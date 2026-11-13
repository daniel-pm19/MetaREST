from __future__ import annotations

import copy
import itertools
import re

import pytest

from app.models.mr import CandidateStatus, DiscardReason, MRCandidate, Verdict
from app.pipeline.embeddings import HashingEmbedder
from app.pipeline.executor import SUTClient
from app.pipeline.filters import FilterSettings
from app.pipeline.llm import FakeLLMProvider, LLMProviderError, LLMRequest, LLMResponse, LLMSettings
from app.pipeline.orchestrator import PipelineSettings, RunReport, StageName, StageStatus, run_pipeline
from app.pipeline.prompts import PromptTemplate
from app.pipeline.wire import to_wire
from tests.conftest import EXAMPLES, FIXTURES, load_example

SPEC_TEXT = (FIXTURES / "openapi_search.yaml").read_text(encoding="utf-8")
EXAMPLE_NAMES = sorted(p.name for p in (EXAMPLES / "specs").glob("*.json"))
_TITLE = re.compile(r'"title": "(.*?)"')


def generated_batch() -> list:
    """4 good examples + a duplicate, an unsupported param, a weak MR and garbage."""
    good = [load_example(n) for n in EXAMPLE_NAMES]
    dup = copy.deepcopy(good[0])
    dup["title"], dup["source"]["query_params"]["q"] = "Duplicada", "rock"
    bad_param = copy.deepcopy(good[1])
    bad_param["title"], bad_param["source"]["query_params"]["color"] = "Parámetro inventado", "red"
    weak = copy.deepcopy(good[2])
    weak["title"] = "Débil"
    return [to_wire(x) for x in [*good, dup, bad_param, weak]] + ["garbage"]


def scripted_llm(fault_scores: dict[str, float] | None = None, check_error: Exception | None = None):
    fault_scores = {"Débil": 0.2, **(fault_scores or {})}

    def respond(req: LLMRequest):
        if "SEMANTIC VALIDITY" in req.system or "FAULT-REVEALING" in req.system:
            if check_error:
                return check_error
            title = _TITLE.search(req.user).group(1)
            score = fault_scores.get(title, 0.8) if "FAULT-REVEALING" in req.system else 0.9
            return {"score": score, "reason": f"razón para {title}"}
        return {"relations": generated_batch()}

    return FakeLLMProvider(respond)


def ids():
    counter = itertools.count(1)
    return lambda: f"c{next(counter)}"


DEFAULT = object()


async def run(llm, *, faults=frozenset(), fake_sut=None, embedder=DEFAULT, settings=None, sut=True, **kw):
    embedder = HashingEmbedder() if embedder is DEFAULT else embedder
    if not sut:
        return await run_pipeline(
            SPEC_TEXT, project_id="p1", run_id="r1", provider=llm, embedder=embedder, sut=None, settings=settings,
            new_id=ids(), **kw,
        )  # fmt: skip
    async with SUTClient("http://sut.test", transport=fake_sut(set(faults)), backoff=0) as client:
        return await run_pipeline(
            SPEC_TEXT, project_id="p1", run_id="r1", provider=llm, embedder=embedder, sut=client, settings=settings,
            new_id=ids(), **kw,
        )  # fmt: skip


def by_title(result) -> dict[str, MRCandidate]:
    return {c.spec.title: c for c in result.candidates if c.spec}


@pytest.mark.asyncio
async def test_full_run_filters_and_executes(fake_sut):
    progress: list[RunReport] = []

    async def on_progress(report: RunReport) -> None:
        progress.append(report)

    llm = scripted_llm()
    result = await run(llm, fake_sut=fake_sut, on_progress=on_progress)
    report = result.report

    assert report.ok, report.error
    assert [s.status for s in report.stages] == [StageStatus.DONE] * 6
    assert result.counts == {
        "pending_review": 4,
        "discarded": 4,
        "not_executable": 1,
        "invalid_semantics": 1,
        "low_fault_revealing": 1,
        "redundant": 1,
    }

    cands = by_title(result)
    first = cands[load_example(EXAMPLE_NAMES[0])["title"]]
    assert cands["Duplicada"].filter_result.reason is DiscardReason.REDUNDANT
    assert cands["Duplicada"].filter_result.duplicate_of == first.id
    assert cands["Duplicada"].scores.max_similarity == 1.0
    assert "'color' no existe" in cands["Parámetro inventado"].filter_result.detail
    assert cands["Parámetro inventado"].scores.semantic_validity.llm_score is None  # rules failed: no LLM call
    assert cands["Débil"].filter_result.detail == "puntuación 0.20 por debajo del umbral 0.50: razón para Débil"
    garbage = next(c for c in result.candidates if c.spec is None)
    assert garbage.raw_output == "garbage" and garbage.status is CandidateStatus.DISCARDED

    pending = [c for c in result.candidates if c.status is CandidateStatus.PENDING_REVIEW]
    assert all(c.filter_result.passed and c.execution.verdict is Verdict.PASS for c in pending)
    assert all(c.scores.combined == 0.85 for c in pending)
    assert all(c.execution is None for c in result.candidates if c.status is CandidateStatus.DISCARDED)
    assert {c.provenance.model for c in result.candidates} == {"claude-sonnet-5-5"}
    assert [c.id for c in result.candidates][:2] == ["c1", "c2"]

    # 1 generation + 6 semantic checks (one MR broke a rule) + 6 fault checks
    assert len(llm.requests) == 13
    assert report.usage.total == 13 * 150
    assert report.stage(StageName.GENERATE).usage.total == 150
    assert {r.model for r in llm.requests[1:]} == {"claude-haiku-5-5"}
    assert report.prompt_versions == {
        "generation": "gen_v1",
        "semantic": "semcheck_v1",
        "fault_revealing": "faultcheck_v1",
    }
    assert (report.verification_model, report.embedder) == ("claude-haiku-5-5", "hashing:256")
    assert report.stage(StageName.EXECUTE).detail == "pass: 4"

    assert progress[0].stage(StageName.EXTRACT).status is StageStatus.RUNNING
    assert progress[-1].finished_at is not None and len(progress) == 13  # start+end per stage, plus final


@pytest.mark.asyncio
async def test_injected_fault_is_reported_as_violation(fake_sut):
    result = await run(scripted_llm(), fake_sut=fake_sut, faults={"order_depends_on_limit"})
    verdict = by_title(result)[load_example(EXAMPLE_NAMES[0])["title"]].execution.verdict
    assert verdict is Verdict.VIOLATION


@pytest.mark.asyncio
async def test_failed_llm_checks_fall_back_to_rules(fake_sut):
    result = await run(scripted_llm(check_error=LLMProviderError("límite de uso", retriable=True)), fake_sut=fake_sut)
    assert result.report.ok
    # without the LLM "Débil" passes the fault stage, then diversity catches it as a copy of example 03
    assert result.counts["pending_review"] == 4
    assert by_title(result)["Débil"].filter_result.reason is DiscardReason.REDUNDANT
    assert any("se usaron solo las reglas" in w for w in result.report.warnings)
    c = next(c for c in result.candidates if c.status is CandidateStatus.PENDING_REVIEW)
    assert c.scores.semantic_validity.score == 1.0 and "límite de uso" in c.scores.semantic_validity.llm_reason


@pytest.mark.asyncio
async def test_rules_only_without_embedder_or_sut():
    settings = PipelineSettings(filters=FilterSettings(use_llm_checks=False))
    llm = scripted_llm()
    result = await run(llm, settings=settings, embedder=None, sut=False)
    report = result.report
    assert len(llm.requests) == 1 and report.verification_model is None
    assert report.stage(StageName.DIVERSITY).status is StageStatus.SKIPPED
    assert report.stage(StageName.EXECUTE).status is StageStatus.SKIPPED
    assert result.counts["pending_review"] == 6  # duplicate and weak MR survive
    assert any("embeddings" in w for w in report.warnings)


@pytest.mark.asyncio
async def test_settings_and_prompt_overrides_are_used():
    settings = PipelineSettings(
        llm=LLMSettings(generation_model="claude-opus-5-5", verification_model="claude-sonnet-5-5", max_candidates=8),
    )
    custom = PromptTemplate.from_strings("semcheck_v1", "CUSTOM SEMANTIC VALIDITY", "{{ mr }}")
    llm = scripted_llm()
    result = await run(llm, settings=settings, sut=False, prompts={"semcheck_v1": custom})
    assert result.report.ok
    assert (llm.requests[0].model, llm.requests[1].model) == ("claude-opus-5-5", "claude-sonnet-5-5")
    assert "8 metamorphic relations" in llm.requests[0].user
    assert any(r.system == "CUSTOM SEMANTIC VALIDITY" for r in llm.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spec, script, failed_stage, error",
    [
        ("openapi: 3.0.0\ninfo: {title: x}\n", {"relations": []}, StageName.EXTRACT, "paths"),
        (
            "openapi: 3.0.0\ninfo: {title: x}\npaths: {/a: {post: {responses: {}}}}\n",
            {"relations": []},
            StageName.EXTRACT,
            "no tiene operaciones GET/HEAD",
        ),
        (
            SPEC_TEXT,
            LLMResponse(model="m", provider="fake", stop_reason="refusal"),
            StageName.GENERATE,
            "la generación falló",
        ),
        (SPEC_TEXT, LLMProviderError("credenciales inválidas"), StageName.GENERATE, "credenciales inválidas"),
    ],
)
async def test_expected_failures_end_the_run_cleanly(spec, script, failed_stage, error):
    result = await run_pipeline(
        spec, project_id="p", run_id="r", provider=FakeLLMProvider(script), embedder=None, sut=None
    )
    report = result.report
    assert not report.ok and error in report.error
    assert report.stage(failed_stage).status is StageStatus.FAILED
    later = report.stages[[s.name for s in report.stages].index(failed_stage) + 1 :]
    assert all(s.status is StageStatus.SKIPPED for s in later)
    assert result.candidates == []


@pytest.mark.asyncio
async def test_unknown_prompt_and_broken_progress_callback():
    async def broken(_report):
        raise RuntimeError("mongo caído")

    settings = PipelineSettings(filters=FilterSettings(fault_prompt="faultcheck_v9"))
    result = await run(scripted_llm(), settings=settings, sut=False, on_progress=broken)
    assert "faultcheck_v9" in result.report.error
    assert result.report.stage(StageName.FAULT_REVEALING).status is StageStatus.FAILED
    assert result.report.stage(StageName.SEMANTIC).status is StageStatus.DONE
