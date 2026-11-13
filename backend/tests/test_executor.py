from __future__ import annotations

import httpx
import pytest

from app.models.mr import MRSpec, RequestSpec, Verdict
from app.pipeline.executor import SUTClient, UnsafeRequestError, build_url, execute_many, execute_mr
from tests.conftest import load_example

BASE = "http://sut.test"


def client(transport: httpx.MockTransport, **kw) -> SUTClient:
    return SUTClient(BASE, transport=transport, backoff=0, **kw)


def mr(**overrides) -> MRSpec:
    base = {
        "title": "Same request twice",
        "description": "Determinism check.",
        "source": {"path": "/search", "query_params": {"q": "jazz", "limit": 5}},
        "followups": [{}],
        "relation": {"type": "equality", "source_selector": "$.results[*].id"},
        "transformation_logic": "none",
        "expected_relation": "S == F",
        "rationale": "Non-deterministic results.",
    }
    base.update(overrides)
    return MRSpec.model_validate(base)


# ─────────────────────────── URL building ──────────────────────────


def test_build_url():
    req = RequestSpec(
        path="/a/{name}/b",
        path_params={"name": "x y/z"},
        query_params={"tags": ["p", "q"], "flag": True, "n": 2.5, "s": "jazz piano"},
    )
    assert build_url(BASE + "/", req) == f"{BASE}/a/x%20y%2Fz/b?tags=p&tags=q&flag=true&n=2.5&s=jazz+piano"
    assert build_url(BASE, RequestSpec(path="/x")) == f"{BASE}/x"


# ─────────────────── doc examples vs. injected faults ───────────────

EXAMPLE_FAULTS = [
    ("01_subset_limit.json", "order_depends_on_limit"),
    ("02_equivalence_sort.json", "desc_drops_last"),
    ("03_count_leq_filter.json", "category_or"),
    ("04_complete_pagination.json", "page_off_by_one"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("example, fault", EXAMPLE_FAULTS)
async def test_examples_pass_on_correct_sut(fake_sut, example, fault):
    spec = MRSpec.model_validate(load_example(example))
    async with client(fake_sut()) as c:
        result = await execute_mr(spec, c)
    assert result.verdict is Verdict.PASS, [i.message for i in result.instances]
    assert len(result.instances) == len(spec.instances())


@pytest.mark.asyncio
@pytest.mark.parametrize("example, fault", EXAMPLE_FAULTS)
async def test_examples_detect_their_fault(fake_sut, example, fault):
    spec = MRSpec.model_validate(load_example(example))
    async with client(fake_sut({fault})) as c:
        result = await execute_mr(spec, c)
    assert result.verdict is Verdict.VIOLATION, [i.message for i in result.instances]


@pytest.mark.asyncio
async def test_evidence_is_recorded(fake_sut):
    spec = MRSpec.model_validate(load_example("01_subset_limit.json"))
    async with client(fake_sut({"order_depends_on_limit"})) as c:
        result = await execute_mr(spec, c)
    inst = next(i for i in result.instances if i.verdict is Verdict.VIOLATION)
    assert inst.source.url == f"{BASE}/search?q=jazz&limit=20"
    assert inst.followups[0].url == f"{BASE}/search?q=jazz&limit=10"
    assert inst.source.status_code == 200 and inst.source.elapsed_ms is not None
    assert inst.source.response_excerpt.startswith('{"total"')
    assert inst.source.selected_excerpt.startswith("[")
    assert "ausentes en la fuente" in inst.message


# ─────────────────────────── errors ────────────────────────────────


@pytest.mark.asyncio
async def test_non_2xx_is_an_error(fake_sut):
    transport = fake_sut(handler=lambda r: httpx.Response(500, text="boom"))
    async with client(transport, max_retries=0) as c:
        result = await execute_mr(mr(), c)
    assert result.verdict is Verdict.ERROR
    assert "HTTP 500" in result.instances[0].message


@pytest.mark.asyncio
async def test_missing_selector_field_is_an_error(fake_sut):
    spec = mr(relation={"type": "equality", "source_selector": "$.items[*].id"})
    async with client(fake_sut()) as c:
        result = await execute_mr(spec, c)
    assert result.verdict is Verdict.ERROR
    assert result.instances[0].message.startswith("fuente: el selector")


@pytest.mark.asyncio
async def test_invalid_json_declared_as_json_is_an_error(fake_sut):
    transport = fake_sut(
        handler=lambda r: httpx.Response(200, text="{oops", headers={"content-type": "application/json"})
    )
    async with client(transport) as c:
        result = await execute_mr(mr(), c)
    assert result.verdict is Verdict.ERROR
    assert "parsear" in result.instances[0].message


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds(fake_sut):
    calls: list[httpx.Request] = []
    state = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"results": [{"id": 1}]})

    async with client(fake_sut(handler=flaky, calls=calls)) as c:
        result = await execute_mr(mr(), c)
    assert result.verdict is Verdict.PASS
    assert len(calls) == 2  # one retry; the follow-up is identical and is deduplicated


@pytest.mark.asyncio
async def test_transport_error_after_retries(fake_sut):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    calls: list[httpx.Request] = []
    async with client(fake_sut(handler=down, calls=calls), max_retries=2) as c:
        result = await execute_mr(mr(), c)
    assert result.verdict is Verdict.ERROR
    assert "ConnectError" in result.instances[0].message
    assert len(calls) == 3


# ─────────────────────────── safety & cache ────────────────────────


@pytest.mark.asyncio
async def test_unsafe_methods_are_refused_even_if_contract_is_bypassed(fake_sut):
    calls: list[httpx.Request] = []
    forged = RequestSpec.model_construct(method="POST", path="/search", path_params={}, query_params={})
    async with client(fake_sut(calls=calls)) as c:
        with pytest.raises(UnsafeRequestError):
            await c.fetch(forged)
    assert calls == []


@pytest.mark.asyncio
async def test_identical_requests_hit_the_sut_once(fake_sut):
    calls: list[httpx.Request] = []
    async with client(fake_sut(calls=calls)) as c:
        first = await execute_mr(mr(), c)  # source == follow-up, fetched concurrently
        second = await execute_mr(mr(), c)  # whole MR again, from cache
    assert first.verdict is Verdict.PASS and second.verdict is Verdict.PASS
    assert len(calls) == 1
    assert c.requests_sent == 1
    assert second.instances[0].source.from_cache


@pytest.mark.asyncio
async def test_failures_are_not_cached(fake_sut):
    state = {"n": 0}

    def fail_once(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(503) if state["n"] == 1 else httpx.Response(200, json={"results": []})

    async with client(fake_sut(handler=fail_once), max_retries=0) as c:
        first = await execute_mr(mr(), c)
        second = await execute_mr(mr(), c)
    assert first.verdict is Verdict.ERROR
    assert second.verdict is Verdict.PASS
    assert "evidencia débil" in second.instances[0].message  # empty selections


@pytest.mark.asyncio
async def test_execute_many_keeps_order(fake_sut):
    specs = [
        mr(),
        mr(relation={"type": "equality", "source_selector": "$.missing"}),
        MRSpec.model_validate(load_example("04_complete_pagination.json")),
    ]
    async with client(fake_sut()) as c:
        results = await execute_many(specs, c, concurrency=2)
    assert [r.verdict for r in results] == [Verdict.PASS, Verdict.ERROR, Verdict.PASS]
