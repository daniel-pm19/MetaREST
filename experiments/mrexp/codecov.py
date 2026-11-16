"""Code coverage of the demo API (coverage.py) exercised by each technique, on the original (no faults).

For each group (traditional tests, manual MRs, MetaREST MRs, all together) the demo API is started under
``coverage run``, the group's items are executed against it, the server is stopped with SIGTERM (coverage saves
its data on SIGTERM with ``sigterm = true``) and the totals are read from ``coverage json``.

SIGTERM is POSIX: on Windows ``terminate()`` kills the process and coverage writes nothing.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mrexp.io import NamedMR
from mrexp.mutants import ORIGINAL, ClientFactory, run_mrs, run_pytest_suite, served


@dataclass
class Group:
    name: str
    mrs: list[NamedMR] = field(default_factory=list)
    tests: Path | None = None


def coverage_command(serve: str, rcfile: Path, data_file: Path) -> str:
    """``serve`` is a module command line (e.g. ``uvicorn app:app --port {port}``), run under coverage."""
    return f'"{sys.executable}" -m coverage run --rcfile "{rcfile}" --data-file "{data_file}" -m {serve}'


def _totals(data_file: Path, workdir: Path, cwd: Path | None) -> dict[str, Any]:
    out = workdir / f"{data_file.name}.json"
    proc = subprocess.run(
        [sys.executable, "-m", "coverage", "json", "--data-file", str(data_file), "-o", str(out), "-q"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"coverage json falló para {data_file.name}: {(proc.stdout + proc.stderr)[-1000:]}")
    totals = json.loads(out.read_text(encoding="utf-8"))["totals"]
    return {
        "lines_covered": totals["covered_lines"],
        "lines_total": totals["num_statements"],
        "branches_covered": totals.get("covered_branches"),
        "branches_total": totals.get("num_branches"),
        "percent": round(totals["percent_covered"], 2),
    }


def _next_free_port(start: int, tries: int = 50) -> int:
    for port in range(start, start + tries):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no hay puertos libres entre {start} y {start + tries - 1}")


async def measure(
    groups: Sequence[Group],
    serve: str,
    source: Path,
    client_factory: ClientFactory,
    *,
    port: int = 8200,
    health_path: str = "/health",
    cwd: Path | None = None,
    concurrency: int = 4,
    pytest_cmd: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        rcfile = workdir / "coveragerc"
        scope = f"include = {source.resolve()}" if source.is_file() else f"source = {source.resolve()}"
        rcfile.write_text(f"[run]\nbranch = true\nsigterm = true\n{scope}\n", encoding="utf-8")
        next_port = port
        for group in groups:
            next_port = _next_free_port(next_port) + 1
            data_file = workdir / f".coverage.{group.name}"
            command = coverage_command(serve, rcfile, data_file)
            not_passing, items = 0, len(group.mrs)
            with served(command, None, port=next_port - 1, health_path=health_path, cwd=cwd) as base_url:
                if group.mrs:
                    results = await run_mrs(group.mrs, ORIGINAL, base_url, client_factory, concurrency=concurrency)
                    not_passing += sum(1 for r in results.values() if r.verdict.value != "pass")
                if group.tests:
                    outcomes = run_pytest_suite(group.tests, base_url, pytest_cmd=pytest_cmd)
                    items += len(outcomes)
                    not_passing += sum(1 for o in outcomes.values() if o != "pass")
            rows.append(
                {"group": group.name, "items": items, "not_passing_original": not_passing}
                | _totals(data_file, workdir, cwd)
            )
    return rows
