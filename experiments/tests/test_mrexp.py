"""Experiment tooling tests: no LLM, no network (in-process fake SUT, plus local stdlib servers for the CLI)."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import httpx
import pytest
from app.models.mr import (
    CandidateStatus,
    DiscardReason,
    FilterOutcome,
    MRCandidate,
    MRSpec,
    Provenance,
)
from app.pipeline.context_extractor import extract_context
from app.pipeline.embeddings import HashingEmbedder
from app.pipeline.executor import SUTClient

from mrexp.__main__ import main
from mrexp.io import NamedMR, RunData, load_manual_mrs, load_run, read_csv, select_candidates, write_csv
from mrexp.metrics import (
    SHEET_COLUMNS,
    cohen_kappa,
    coverage_rows,
    join_labels,
    key,
    label_sheet_rows,
    parse_label,
    redundant_unique_detection_rows,
    rq1_by_stage_rows,
    rq1_rows,
    rq2_rows,
)
from mrexp.mutants import (
    ORIGINAL,
    detection_rows,
    detects,
    mr_items,
    parse_junit,
    run_mrs,
    summary_rows,
    verdicts_to_outcomes,
)

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
REPO = HERE.parents[1]
EXAMPLES = REPO / "docs" / "mr_examples" / "specs"
SEARCH_SPEC = REPO / "backend" / "tests" / "fixtures" / "openapi_search.yaml"
FAULTS = ["page_off_by_one", "category_or", "desc_drops_last", "wrong_item_name"]

sys.path.insert(0, str(FIXTURES))
import demo_sut  # noqa: E402


def example(name: str) -> MRSpec:
    return MRSpec.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))


def candidate(cid: str, spec: MRSpec | None, reason: DiscardReason | None = None, *, dup: str | None = None, **kw):
    outcome = (
        FilterOutcome(passed=True) if reason is None else FilterOutcome(passed=False, reason=reason, duplicate_of=dup)
    )
    status = CandidateStatus.DISCARDED if reason else kw.pop("status", CandidateStatus.PENDING_REVIEW)
    return MRCandidate(
        id=cid,
        project_id="p",
        run_id=kw.pop("run_id", "r1"),
        spec=spec,
        raw_output=kw.pop("raw_output", None),
        provenance=Provenance(provider="fake", model="fake-model", prompt_version="gen_v1"),
        filter_result=outcome,
        status=status,
    )


def run_of(*candidates: MRCandidate, threshold: float = 0.975) -> RunData:
    return RunData(Path("run.json"), {"filters": {"similarity_threshold": threshold}}, {}, list(candidates))


def write_run(path: Path, run: RunData) -> Path:
    candidates = [c.model_dump(mode="json") for c in run.candidates]
    path.write_text(json.dumps({"settings": run.settings, "report": {}, "candidates": candidates}), encoding="utf-8")
    return path


@pytest.fixture
def run() -> RunData:
    subset = example("01_subset_limit.json")
    other_values = subset.model_copy(
        update={"source": subset.source.model_copy(update={"query_params": {"q": "pop", "limit": 20}})}
    )
    return run_of(
        candidate("ok1", subset, status=CandidateStatus.ACCEPTED),
        candidate("ok2", example("04_complete_pagination.json")),
        candidate("sem", example("02_equivalence_sort.json"), DiscardReason.INVALID_SEMANTICS),
        candidate("dup", other_values, DiscardReason.REDUNDANT, dup="ok1"),
        candidate("bad", None, DiscardReason.NOT_EXECUTABLE, raw_output={"title": "Rota", "description": "x"}),
    )


# ───────────────────────────── RQ1 ──────────────────────────────


def test_cohen_kappa():
    t, f = True, False
    assert cohen_kappa([(t, t), (t, f), (f, f), (f, f)]) == pytest.approx(0.5)
    assert cohen_kappa([(t, t), (f, f)]) == pytest.approx(1.0)
    assert cohen_kappa([(t, t), (t, t)]) == 1.0  # degenerate: a single label
    assert cohen_kappa([(t, f), (f, t)]) == pytest.approx(-1.0)
    assert cohen_kappa([]) is None


@pytest.mark.parametrize("text, value", [("1", True), ("Sí", True), (" no ", False), ("0", False), ("", None)])
def test_parse_label(text, value):
    assert parse_label(text) is value


def test_parse_label_rejects_unknown():
    with pytest.raises(ValueError, match="r1/x label_a"):
        parse_label("quizás", "r1/x label_a")


def test_label_sheet_is_blind_complete_and_reproducible(run):
    rows = label_sheet_rows([run])
    assert {r["key"] for r in rows} == {key(c) for c in run.candidates}
    assert set(SHEET_COLUMNS) >= set().union(*(r.keys() for r in rows))
    leaks = {"status", "filter", "score", "verdict", "reason", "duplicate_of"}
    assert not any(word in col for col in SHEET_COLUMNS for word in leaks)
    bad = next(r for r in rows if r["key"] == "r1/bad")
    assert (bad["label_a"], bad["label_b"], bad["title"]) == ("0", "0", "Rota")
    ok1 = next(r for r in rows if r["key"] == "r1/ok1")
    assert "GET /search?q=jazz&limit=20" in ok1["source_requests"] and "limit=10" in ok1["followup_requests"]
    assert [r["key"] for r in label_sheet_rows([run])] == [r["key"] for r in rows]  # fixed seed


def test_rq1_rates_confusion_and_kappa(run):
    labels = {
        "ok1": ("1", "1", ""),
        "ok2": ("1", "0", "0"),  # disagreement resolved by label_final
        "sem": ("1", "1", ""),  # a valid MR the filter discarded
        "dup": ("1", "0", ""),  # unresolved
        "bad": ("0", "0", ""),
    }
    sheet = [{"key": f"r1/{k}", "label_a": a, "label_b": b, "label_final": f} for k, (a, b, f) in labels.items()]
    labeled = join_labels([run], sheet)
    row = rq1_rows(labeled)
    assert (row["labeled"], row["disagreements_unresolved"], row["unlabeled"]) == (4, 1, 0)
    assert row["valid_rate_pre"] == pytest.approx(2 / 4)  # ok1, sem valid; ok2, bad invalid
    assert row["valid_rate_post"] == pytest.approx(1 / 2)  # ok1 valid, ok2 invalid
    assert (row["kept_valid"], row["kept_invalid"], row["discarded_valid"], row["discarded_invalid"]) == (1, 1, 1, 1)
    assert row["kappa"] == pytest.approx(
        cohen_kappa([(True, True), (True, False), (True, True), (True, False), (False, False)])
    )
    assert row["valid_rate_pre_a"] == pytest.approx(4 / 5)
    stages = {r["outcome"]: r for r in rq1_by_stage_rows(labeled)}
    assert stages["invalid_semantics"]["labeled_valid"] == 1 and stages["redundant"]["not_agreed"] == 1
    assert list(stages)[0] == "passed"


# ───────────────────────────── RQ2 ──────────────────────────────


@pytest.mark.asyncio
async def test_rq2_counts_redundancy_before_but_not_after_diversity(run):
    summary, clusters = await rq2_rows([run], HashingEmbedder())
    by_set = {r["set"]: r for r in summary}
    assert by_set["pre_diversity"]["mrs"] == 3  # ok1, ok2, dup (sem was dropped earlier, bad has no spec)
    assert by_set["pre_diversity"]["redundant_mrs"] == 1  # dup has the same signature as ok1
    assert by_set["post_diversity"]["redundant_mrs"] == 0
    assert by_set["generated"]["mrs"] == 4
    assert any(sorted(c["members"]) == ["dup", "ok1"] for c in clusters if c["set"] == "pre_diversity")
    assert {r["threshold"] for r in summary} == {0.975}

    summary, _ = await rq2_rows([run], HashingEmbedder(), [0.5, 0.99])
    assert {r["threshold"] for r in summary} == {0.5, 0.99}


def test_unique_detections_of_redundant_mrs():
    rows = [
        {"technique": "metarest", "item_id": "a", "filter_reason": "", "variant": "f1", "detected": "1"},
        {"technique": "metarest", "item_id": "d", "filter_reason": "redundant", "variant": "f1", "detected": "1"},
        {"technique": "metarest", "item_id": "d", "filter_reason": "redundant", "variant": "f2", "detected": "1"},
        {"technique": "metarest", "item_id": "a", "filter_reason": "", "variant": "f2", "detected": "0"},
        {"technique": "manual", "item_id": "m", "filter_reason": "", "variant": "f2", "detected": "1"},
        {"technique": "metarest", "item_id": "a", "filter_reason": "", "variant": ORIGINAL, "detected": "0"},
    ]
    out = {r["fault"]: r for r in redundant_unique_detection_rows(rows)}
    assert out["f1"]["only_redundant_detect"] is False
    assert out["f2"]["only_redundant_detect"] is True and out["f2"]["redundant_items"] == ["d"]


# ─────────────────────────── coverage ────────────────────────────


def test_coverage_counts_documented_operations_and_params(run):
    context = extract_context(SEARCH_SPEC.read_text(encoding="utf-8"))
    groups = {"selected": [m.spec for m in select_candidates([run], "passed")]}
    summary, uncovered = coverage_rows(context, groups)
    row = summary[0]
    assert (row["ops_covered"], row["ops_total"]) == (1, 3)  # only /search; /items/{id} and HEAD /tags missed
    assert (row["params_covered"], row["params_total"]) == (4, 6)  # q, limit, page, sort of 5 + items id
    missing = {(u["kind"], u["path"], u["param"]) for u in uncovered}
    assert ("param", "/search", "query:category") in missing and ("operation", "/items/{id}", "") in missing
    assert ("param", "/items/{id}", "path:id") not in missing  # implied by the uncovered operation


# ─────────────────────────── selection ───────────────────────────


def test_select_candidates(run):
    assert [m.id for m in select_candidates([run], "accepted")] == ["ok1"]
    assert [m.id for m in select_candidates([run], "passed")] == ["ok1", "ok2"]
    every = {m.id: m for m in select_candidates([run], "all")}
    assert set(every) == {"ok1", "ok2", "sem", "dup"} and every["dup"].filter_reason == "redundant"


def test_load_run_and_manual_mrs(tmp_path, run):
    path = write_run(tmp_path / "run.json", run)
    assert [c.id for c in load_run(path).candidates] == [c.id for c in run.candidates]

    manual = tmp_path / "manual"
    manual.mkdir()
    (manual / "pagination.json").write_text((EXAMPLES / "04_complete_pagination.json").read_text(), encoding="utf-8")
    pair = [json.loads((EXAMPLES / n).read_text()) for n in ("02_equivalence_sort.json", "03_count_leq_filter.json")]
    (manual / "pair.json").write_text(json.dumps(pair), encoding="utf-8")
    assert [m.id for m in load_manual_mrs(manual)] == ["pagination", "pair#1", "pair#2"]

    (manual / "broken.json").write_text(json.dumps({"title": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="broken.json"):
        load_manual_mrs(manual)


# ─────────────────────────── mutants (RQ3) ───────────────────────────


def in_process_factory(variant: str, base_url: str) -> SUTClient:
    faults = set() if variant == ORIGINAL else {variant}

    def handler(request: httpx.Request) -> httpx.Response:
        status, body = demo_sut.respond(request.url.path, dict(request.url.params), faults)
        return httpx.Response(status, json=body)

    return SUTClient(base_url, transport=httpx.MockTransport(handler))


def named(*names: str) -> list[NamedMR]:
    return [NamedMR(id=n, title=n, spec=example(n), technique="manual", status="manual") for n in names]


@pytest.mark.asyncio
async def test_mr_detection_matrix_in_process():
    mrs = named(*(p.name for p in sorted(EXAMPLES.glob("*.json"))))
    per_variant = {v: await run_mrs(mrs, v, "http://demo", in_process_factory) for v in (ORIGINAL, *FAULTS)}
    outcomes: dict = {}
    verdicts_to_outcomes("manual", per_variant, outcomes)
    assert all(per_variant[ORIGINAL][m.id].verdict.value == "pass" for m in mrs)

    rows = detection_rows(mr_items(mrs), outcomes, FAULTS)
    hit = {(r["item_id"], r["variant"]) for r in rows if r["detected"]}
    assert ("04_complete_pagination.json", "page_off_by_one") in hit
    assert ("03_count_leq_filter.json", "category_or") in hit
    assert ("02_equivalence_sort.json", "desc_drops_last") in hit
    assert not any(v == "wrong_item_name" for _, v in hit)  # no MR reads /items/{id}
    assert not any(v == ORIGINAL for _, v in hit)

    (row,) = summary_rows(mr_items(mrs), outcomes, FAULTS)
    assert (row["combination"], row["faults_detected"], row["missed"]) == ("manual", 3, ["wrong_item_name"])


def test_detection_rule():
    assert detects({ORIGINAL: "pass", "f": "violation"}, "f")
    assert detects({ORIGINAL: "pass", "f": "error"}, "f")
    assert not detects({ORIGINAL: "pass", "f": "error"}, "f", strict=True)
    assert detects({ORIGINAL: "pass", "f": "fail"}, "f", strict=True)
    assert not detects({ORIGINAL: "violation", "f": "violation"}, "f")  # broken on the original: not a detection
    assert not detects({ORIGINAL: "pass", "f": "skip"}, "f")
    assert not detects({ORIGINAL: "pass"}, ORIGINAL)


def test_parse_junit(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite name="s">'
        '<testcase classname="t.m" name="ok"/>'
        '<testcase classname="t.m" name="bad"><failure message="x"/></testcase>'
        '<testcase classname="t.m" name="boom"><error message="y"/></testcase>'
        '<testcase classname="t.m" name="later"><skipped/></testcase>'
        "</testsuite></testsuites>"
    )
    assert parse_junit(xml) == {"t.m::ok": "pass", "t.m::bad": "fail", "t.m::boom": "error", "t.m::later": "skip"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_cli_end_to_end_with_served_variants(tmp_path, run):
    """Real processes: one stdlib server per variant, the example traditional suite and manual + MetaREST MRs."""
    run_file = write_run(tmp_path / "run.json", run)
    manual = tmp_path / "manual"
    manual.mkdir()
    for n in ("02_equivalence_sort.json", "03_count_leq_filter.json"):
        (manual / n).write_text((EXAMPLES / n).read_text(), encoding="utf-8")

    port = free_port()
    out = tmp_path / "results"
    main(
        [
            "mutants",
            "--run", str(run_file),
            "--manual", str(manual),
            "--tests", str(FIXTURES / "traditional" / "check_demo_api.py"),
            "--serve", f"{sys.executable} {FIXTURES / 'demo_sut.py'} --port {{port}}",
            "--faults", ",".join(FAULTS),
            "--port", str(port),
            "--name", "demo",
            "--out-dir", str(out),
            "--raw-dir", str(tmp_path / "raw"),
        ]
    )  # fmt: skip

    summary = {r["combination"]: r for r in read_csv(out / "demo_rq3_summary.csv")}
    assert summary["traditional"]["detected"] == "wrong_item_name"
    assert summary["manual"]["detected"] == "category_or; desc_drops_last"
    assert summary["metarest"]["detected"] == "page_off_by_one"  # ok1 + ok2 (passed) only
    assert summary["traditional+manual+metarest"]["faults_detected"] == "4"
    assert summary["traditional+metarest"]["faults_detected"] == "2"
    matrix = {r["fault"]: r for r in read_csv(out / "demo_rq3_fault_matrix.csv")}
    assert matrix["page_off_by_one"]["metarest"] == "2" and matrix["wrong_item_name"]["traditional"] == "1"
    detections = read_csv(out / "demo_detections.csv")
    assert {r["variant"] for r in detections} == {ORIGINAL, *FAULTS}
    evidence = json.loads((tmp_path / "raw" / "demo_mutants.json").read_text())
    assert set(evidence["mrs"]["metarest"]) == {ORIGINAL, *FAULTS} and len(evidence["tests"]) == 5


def test_cli_metrics_commands(tmp_path, run):
    run_file = write_run(tmp_path / "run.json", run)
    out = tmp_path / "results"
    common = ["--name", "t", "--out-dir", str(out)]

    main(["label-sheet", str(run_file), *common])
    sheet = read_csv(out / "t_labels.csv")
    assert len(sheet) == 5
    rows = [{**r, "label_a": r["label_a"] or "1", "label_b": r["label_b"] or "1"} for r in sheet]
    write_csv(out / "filled.csv", rows, SHEET_COLUMNS)
    main(["rq1", str(run_file), "--labels", str(out / "filled.csv"), *common])
    assert read_csv(out / "t_rq1.csv")[0]["valid_rate_post"] == "1.0"

    main(["rq2", str(run_file), "--embedder", "hashing", *common])
    assert len(read_csv(out / "t_rq2.csv")) == 3

    main(["coverage", str(SEARCH_SPEC), str(run_file), *common])
    groups = {r["group"] for r in read_csv(out / "t_coverage.csv")}
    assert groups == {"metarest_generated", "metarest_selected", "metarest_accepted"}


def test_rq1_warns_about_runs_with_failed_checks(tmp_path, run, capsys):
    run.report = {"warnings": ["3 chequeos LLM de la etapa semantic fallaron; se usaron solo las reglas"]}
    run_file = write_run(tmp_path / "run.json", run)
    data = json.loads(run_file.read_text())
    data["report"] = run.report
    run_file.write_text(json.dumps(data))
    main(["label-sheet", str(run_file), "--name", "w", "--out-dir", str(tmp_path)])
    main(["rq1", str(run_file), "--labels", str(tmp_path / "w_labels.csv"), "--name", "w", "--out-dir", str(tmp_path)])
    assert "OJO: run tuvo chequeos LLM fallidos" in capsys.readouterr().out
