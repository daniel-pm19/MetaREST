"""RQ3: which injected faults each technique detects on the demo API.

A *variant* is one running instance of the demo API: ``original`` (no faults) or one per fault
(``FAULTS=<name>``). Each item (an MR or a traditional test) gets an outcome per variant:

* MRs: ``pass | violation | error | skipped`` (the pipeline executor's verdict).
* Traditional tests (pytest + junit XML): ``pass | fail | error | skip``.

An item **detects** a fault when it passes on ``original`` and does not pass on that fault's variant.
Requiring ``pass`` on the original discards items that are broken anyway (a wrong MR, a flaky test) and
treats MRs and tests the same way. With ``strict=True`` only ``violation``/``fail`` count (not ``error``).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import httpx
from app.models.mr import ExecutionResult
from app.pipeline.executor import SUTClient, execute_many

from mrexp.io import NamedMR

ORIGINAL = "original"
TECHNIQUES = ("traditional", "manual", "metarest")
DETECTING = {"violation", "error", "fail"}
DETECTING_STRICT = {"violation", "fail"}

ClientFactory = Callable[[str, str], SUTClient]  # (variant, base_url) -> client


def default_client_factory(timeout: float = 10.0, max_concurrency: int = 4) -> ClientFactory:
    def make(variant: str, base_url: str) -> SUTClient:
        return SUTClient(base_url, timeout=timeout, max_concurrency=max_concurrency)

    return make


@dataclass(frozen=True)
class Item:
    technique: str
    id: str
    title: str
    status: str = ""
    filter_reason: str = ""


Outcomes = dict[tuple[str, str], dict[str, str]]  # (technique, item id) -> variant -> outcome


# ───────────────────────────── MRs ──────────────────────────────


async def run_mrs(
    mrs: Sequence[NamedMR], variant: str, base_url: str, client_factory: ClientFactory, *, concurrency: int = 4
) -> dict[str, ExecutionResult]:
    """Execute every MR against one variant (fresh client: the response cache must not leak across variants)."""
    if not mrs:
        return {}
    async with client_factory(variant, base_url) as client:
        results = await execute_many([m.spec for m in mrs], client, concurrency=concurrency)
    return {m.id: r for m, r in zip(mrs, results, strict=True)}


def mr_items(mrs: Sequence[NamedMR]) -> list[Item]:
    return [Item(m.technique, m.id, m.title, m.status, m.filter_reason) for m in mrs]


# ─────────────────────── traditional tests ───────────────────────


def parse_junit(path: Path) -> dict[str, str]:
    """junit XML -> {test id: pass|fail|error|skip}. Test id = ``classname::name``."""
    outcomes: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}".lstrip(":")
        if case.find("failure") is not None:
            outcome = "fail"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skip"
        else:
            outcome = "pass"
        outcomes[test_id] = outcome
    return outcomes


def run_pytest_suite(
    tests: Path, base_url: str, *, pytest_cmd: str | None = None, env_var: str = "SUT_BASE_URL", timeout: float = 900
) -> dict[str, str]:
    """Run the traditional suite against one variant; the suite reads the SUT URL from ``env_var``.

    A failing suite is expected (that is the point); only a missing junit report is an error.
    """
    cmd = shlex.split(pytest_cmd) if pytest_cmd else [sys.executable, "-m", "pytest"]
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        args = [*cmd, str(tests), f"--junitxml={junit}", "-q", "-p", "no:cacheprovider"]
        proc = subprocess.run(
            args, env={**os.environ, env_var: base_url}, capture_output=True, text=True, timeout=timeout
        )
        if not junit.exists():
            tail = (proc.stdout + proc.stderr)[-2000:]
            raise RuntimeError(f"pytest no generó el reporte junit (código {proc.returncode}):\n{tail}")
        return parse_junit(junit)


# ─────────────────────── serving variants ───────────────────────


@contextmanager
def served(
    cmd_template: str,
    fault: str | None,
    *,
    port: int,
    health_path: str = "/health",
    faults_env: str = "FAULTS",
    startup_timeout: float = 30.0,
    cwd: Path | None = None,
) -> Iterator[str]:
    """Start one demo-API process with ``FAULTS=<fault>`` (empty for the original) and yield its base URL.

    ``cmd_template`` is formatted with ``{port}``, e.g. ``uvicorn app.main:app --port {port}``.
    """
    env = {**os.environ, faults_env: fault or ""}
    proc = subprocess.Popen(
        shlex.split(cmd_template.format(port=port)),
        env=env,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + startup_timeout
        while True:
            if proc.poll() is not None:
                err = proc.stderr.read()[-2000:] if proc.stderr else ""
                raise RuntimeError(f"el servidor de la variante {fault or ORIGINAL!r} terminó al arrancar:\n{err}")
            try:
                if httpx.get(base_url + health_path, timeout=1.0).status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"la variante {fault or ORIGINAL!r} no respondió en {startup_timeout:g} s")
            time.sleep(0.2)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.stderr:
            proc.stderr.close()


# ─────────────────────────── detection ───────────────────────────


def detects(outcomes: dict[str, str], variant: str, *, strict: bool = False) -> bool:
    if variant == ORIGINAL or outcomes.get(ORIGINAL) != "pass":
        return False
    return outcomes.get(variant) in (DETECTING_STRICT if strict else DETECTING)


def detection_rows(
    items: Sequence[Item], outcomes: Outcomes, faults: Sequence[str], *, strict: bool = False
) -> list[dict]:
    """Long format: one row per (item, variant). The CSV every other table is derived from."""
    rows = []
    for item in items:
        per_variant = outcomes.get((item.technique, item.id), {})
        for variant in (ORIGINAL, *faults):
            rows.append(
                {
                    "technique": item.technique,
                    "item_id": item.id,
                    "title": item.title,
                    "status": item.status,
                    "filter_reason": item.filter_reason,
                    "variant": variant,
                    "outcome": per_variant.get(variant, ""),
                    "detected": detects(per_variant, variant, strict=strict),
                }
            )
    return rows


def detected_by(items: Sequence[Item], outcomes: Outcomes, faults: Sequence[str], *, strict: bool = False):
    """{technique: {fault: {item ids that detect it}}}."""
    out: dict[str, dict[str, set[str]]] = {}
    for item in items:
        per_variant = outcomes.get((item.technique, item.id), {})
        by_fault = out.setdefault(item.technique, {f: set() for f in faults})
        for fault in faults:
            if detects(per_variant, fault, strict=strict):
                by_fault[fault].add(item.id)
    return out


def combination_names(present: Sequence[str]) -> list[tuple[str, ...]]:
    techniques = [t for t in TECHNIQUES if t in present]
    return [combo for n in range(1, len(techniques) + 1) for combo in combinations(techniques, n)]


def summary_rows(
    items: Sequence[Item], outcomes: Outcomes, faults: Sequence[str], *, strict: bool = False
) -> list[dict]:
    """One row per technique combination (a) traditional, (b) +manual, (c) +MetaREST, and the rest."""
    table = detected_by(items, outcomes, faults, strict=strict)
    counts = {t: sum(1 for i in items if i.technique == t) for t in table}
    broken = {
        t: sum(1 for i in items if i.technique == t and outcomes.get((t, i.id), {}).get(ORIGINAL) != "pass")
        for t in table
    }
    rows = []
    for combo in combination_names(list(table)):
        hit = [f for f in faults if any(table[t][f] for t in combo)]
        rows.append(
            {
                "combination": "+".join(combo),
                "items": sum(counts[t] for t in combo),
                "items_not_passing_original": sum(broken[t] for t in combo),
                "faults_detected": len(hit),
                "faults_total": len(faults),
                "detection_rate": len(hit) / len(faults) if faults else 0.0,
                "detected": sorted(hit),
                "missed": [f for f in faults if f not in hit],
            }
        )
    return rows


def fault_matrix_rows(
    items: Sequence[Item], outcomes: Outcomes, faults: Sequence[str], *, strict: bool = False
) -> list[dict]:
    """Fault x technique: how many items of each technique detect each fault (0 = missed)."""
    table = detected_by(items, outcomes, faults, strict=strict)
    return [{"fault": f, **{t: len(table[t][f]) for t in TECHNIQUES if t in table}} for f in faults]


def verdicts_to_outcomes(technique: str, per_variant: dict[str, dict[str, ExecutionResult]], into: Outcomes) -> None:
    for variant, results in per_variant.items():
        for mr_id, result in results.items():
            into.setdefault((technique, mr_id), {})[variant] = result.verdict.value


def tests_to_outcomes(per_variant: dict[str, dict[str, str]], into: Outcomes) -> list[Item]:
    ids: list[str] = []
    for variant, results in per_variant.items():
        for test_id, outcome in results.items():
            into.setdefault(("traditional", test_id), {})[variant] = outcome
            if test_id not in ids:
                ids.append(test_id)
    return [Item("traditional", t, t.rsplit("::", 1)[-1], "test") for t in ids]
