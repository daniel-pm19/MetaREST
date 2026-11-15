import importlib.util
from pathlib import Path

import httpx
import pytest

from app.models.mr import MRSpec, Verdict
from app.pipeline.executor import SUTClient, execute_many

ROOT = Path(__file__).resolve().parents[2]


def demo_module():
    spec = importlib.util.spec_from_file_location("metarest_demo_sut", ROOT / "sut-demo/app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "filter_or",
        "wrong_total",
        "repeat_page",
        "drop_on_sort",
        "ignore_limit",
        "page_off_by_one",
        "ignore_category",
        "limit_dependent_order",
    ],
)
async def test_demo_matches_shared_contract_and_runs_team_executor(fault):
    app = demo_module().create_app({fault} if fault else set())
    specs = [
        MRSpec.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((ROOT / "docs/mr_examples/specs").glob("*.json"))
    ]
    async with SUTClient("http://sut", transport=httpx.ASGITransport(app=app)) as sut:
        results = await execute_many(specs, sut)
    assert len(results) == 4
    if fault is None or fault == "ignore_category":
        assert all(result.verdict == Verdict.PASS for result in results)
    else:
        assert any(result.verdict == Verdict.VIOLATION for result in results)


async def test_demo_context_has_examples_and_response_fields():
    from app.pipeline.context_extractor import extract_context

    context = extract_context(demo_module().create_app(set()).openapi())
    operation = context.find_operation("GET", "/search")
    assert operation.param("q").example == "jazz"
    assert operation.param("limit").maximum == 100
    assert operation.param("category").enum == ["vinyl", "cd"]
    assert operation.response_fields["$.results[*].id"] == "integer"


def test_unknown_fault_does_not_start_silently():
    with pytest.raises(ValueError, match="Unknown FAULTS"):
        demo_module().create_app({"unknown"})
