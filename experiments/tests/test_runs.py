"""`mrexp run` without the real LLM: fake provider + in-process demo SUT."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from app.pipeline.embeddings import HashingEmbedder
from app.pipeline.executor import SUTClient
from app.pipeline.llm import FakeLLMProvider, LLMProviderError, LLMRequest
from app.pipeline.wire import to_wire

from mrexp.__main__ import main
from mrexp.io import load_run
from mrexp.runs import FROZEN_CONFIG, execute_run, load_settings, write_export
from mrexp.suts import SUTPreset

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "docs" / "mr_examples" / "specs"
SEARCH_SPEC = REPO / "backend" / "tests" / "fixtures" / "openapi_search.yaml"
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import demo_sut  # noqa: E402

PRESET = SUTPreset(SEARCH_SPEC, "http://demo")


def llm(check_error: Exception | None = None) -> FakeLLMProvider:
    batch = [to_wire(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(EXAMPLES.glob("*.json"))]

    def respond(req: LLMRequest):
        if "SEMANTIC VALIDITY" in req.system or "FAULT-REVEALING" in req.system:
            return check_error or {"score": 0.9, "reason": "ok"}
        return {"relations": batch}

    return FakeLLMProvider(respond)


def demo_client() -> SUTClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = demo_sut.respond(request.url.path, dict(request.url.params), set())
        return httpx.Response(status, json=body)

    return SUTClient("http://demo", transport=httpx.MockTransport(handler))


def test_frozen_config_is_the_calibrated_gemini_setup():
    s = load_settings(FROZEN_CONFIG)
    assert (s.llm.provider, s.llm.generation_model, s.llm.verification_model) == (
        "gemini",
        "gemini-4-hydrogen",
        "gemini-3.5-flash-lite",
    )
    assert s.llm.verification_effort == "medium" and s.llm.max_candidates == 20
    assert (s.generation_prompt, s.filters.semantic_prompt, s.filters.fault_prompt) == (
        "gen_v1",
        "semcheck_v2",
        "faultcheck_v2",
    )
    # every field is written out, so a later change of a code default cannot change the experiment
    assert set(json.loads(FROZEN_CONFIG.read_text())["llm"]) == set(type(s.llm).model_fields)


@pytest.mark.asyncio
async def test_run_export_is_readable_by_the_metrics(tmp_path):
    settings = load_settings(FROZEN_CONFIG)
    result, payload = await execute_run(
        "demo_run1", "demo", PRESET, settings, llm(), HashingEmbedder(), client=demo_client(), config_path=FROZEN_CONFIG
    )
    meta = payload["meta"]
    assert meta["usable"] and meta["problems"] == []
    assert meta["spec_sha256"] and meta["config_sha256"] and meta["sut"] == "demo"
    path = tmp_path / "demo_run1.json"
    write_export(payload, path)
    run = load_run(path)
    assert len(run.candidates) == len(result.candidates) == 4
    assert all(c.execution and c.execution.verdict.value == "pass" for c in run.candidates if c.filter_result.passed)
    assert run.settings["llm"]["generation_model"] == "gemini-4-hydrogen"


@pytest.mark.asyncio
async def test_failed_checks_make_the_run_unusable():
    settings = load_settings(FROZEN_CONFIG)
    _, payload = await execute_run(
        "r", "demo", PRESET, settings, llm(LLMProviderError("cuota")), HashingEmbedder(), client=demo_client()
    )
    assert not payload["meta"]["usable"]
    assert any("chequeos LLM" in p for p in payload["meta"]["problems"])


def test_run_cli_guards(tmp_path):
    with pytest.raises(SystemExit, match="--name"):
        main(["run", "pokeapi"])
    with pytest.raises(SystemExit, match="SUT desconocida"):
        main(["run", "demo", "--name", "demo_run1"])
    (tmp_path / "pokeapi_run1.json").write_text("{}")
    with pytest.raises(SystemExit, match="no se sobrescribe"):
        main(["run", "pokeapi", "--name", "pokeapi_run1", "--raw-dir", str(tmp_path)])
