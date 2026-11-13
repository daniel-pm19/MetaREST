"""Calibration tooling without the real LLM: fake provider + in-process demo SUT."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from app.models.mr import Direction, MRSpec, RelationType
from app.pipeline.context_extractor import extract_context
from app.pipeline.executor import SUTClient
from app.pipeline.llm.fake import FakeLLMProvider

from mrexp.calibration import CheckConfig, auc, build_items, execute_items, mutate, run_checks, summary_rows
from mrexp.io import RunData

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "docs" / "mr_examples" / "specs"
SEARCH_SPEC = REPO / "backend" / "tests" / "fixtures" / "openapi_search.yaml"
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import demo_sut  # noqa: E402


def example(name: str) -> MRSpec:
    return MRSpec.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))


def test_mutate_flips_or_swaps_and_rewrites_the_claim():
    op, m = mutate(example("01_subset_limit.json"))
    assert op == "flip_direction" and m.relation.direction is Direction.SOURCE_IN_FOLLOWUP
    op, m = mutate(example("04_complete_pagination.json"))
    assert op == "complete_to_disjoint" and m.relation.type is RelationType.DISJOINT
    assert "no comparten" in m.expected_relation and m.description == m.expected_relation
    assert m.source == example("04_complete_pagination.json").source  # same requests, other claim


def test_auc():
    assert auc([1.0, 0.9], [0.1, 0.2]) == 1.0
    assert auc([0.5], [0.5]) == 0.5
    assert auc([0.2], [0.9]) == 0.0
    assert auc([], [0.1]) is None


def test_check_config_parse():
    assert CheckConfig.parse("gemini-4-hydrogen:medium") == CheckConfig("gemini-4-hydrogen", "medium", "v1")
    assert CheckConfig.parse("m").effort == "low" and CheckConfig.parse("m:none").effort is None
    assert CheckConfig.parse("m:high:v2").name == "m:high:v2"


@pytest.mark.asyncio
async def test_items_are_labeled_by_execution_and_scored():
    from app.models.mr import FilterOutcome, MRCandidate, Provenance

    names = [
        "01_subset_limit.json",
        "02_equivalence_sort.json",
        "03_count_leq_filter.json",
        "04_complete_pagination.json",
    ]
    run = RunData(
        Path("r.json"),
        {},
        {},
        [
            MRCandidate(
                id=f"{i:08d}",
                project_id="p",
                run_id="r",
                spec=example(n),
                provenance=Provenance(provider="fake", model="m", prompt_version="gen_v1"),
                filter_result=FilterOutcome(passed=True),
            )
            for i, n in enumerate(names)
        ],
    )
    ctx = extract_context(SEARCH_SPEC.read_text(encoding="utf-8"))
    items = build_items("demo", run, ctx)
    assert [i.kind for i in items].count("mutant") == 4

    def handler(request: httpx.Request) -> httpx.Response:
        status, body = demo_sut.respond(request.url.path, dict(request.url.params), set())
        return httpx.Response(status, json=body)

    async with SUTClient("http://demo", transport=httpx.MockTransport(handler)) as client:
        await execute_items(items, client, concurrency=2)
    labels = {(i.kind, i.operator): i.label for i in items}
    assert all(i.label == "valid" for i in items if i.kind == "original")
    assert labels[("mutant", "complete_to_disjoint")] == "invalid"
    assert labels[("mutant", "equivalence_to_disjoint")] == "invalid"

    def score(request):  # a perfect fake checker: low score for the mutants' claims
        return {"score": 0.1 if "(variante)" in request.user else 0.9, "reason": "ok"}

    config = CheckConfig("fake-model", "low")
    await run_checks(items, {"demo": ctx}, FakeLLMProvider(score), config)
    (row,) = summary_rows(items, [config.name])
    assert row["sem_auc"] == 1.0 and row["errors"] == 0
    assert row["keep_valid@0.6"] == 1.0 and row["drop_invalid@0.6"] == 1.0
