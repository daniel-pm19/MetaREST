"""Run traditional tests against the original demo and each injected fault (no LLM)."""

import argparse
import json
import shlex
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from mrexp.mutants import run_pytest_suite, served  # noqa: E402

FAULTS = (
    "filter_or",
    "wrong_total",
    "repeat_page",
    "drop_on_sort",
    "ignore_limit",
    "page_off_by_one",
    "ignore_category",
    "limit_dependent_order",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "experiments/raw/traditional-demo.json")
    args = parser.parse_args()
    command = shlex.join(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:create_app",
            "--factory",
            "--app-dir",
            str(ROOT / "sut-demo"),
            "--host",
            "127.0.0.1",
            "--port",
            "{port}",
        ]
    )
    outcomes = {}
    for fault in (None, *FAULTS):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with served(command, fault, port=port, cwd=ROOT):
            outcomes[fault or "original"] = run_pytest_suite(ROOT / "sut-demo/tests", f"http://127.0.0.1:{port}")
        print(f"{fault or 'original'}: {list(outcomes[fault or 'original'].values()).count('pass')} passed", flush=True)
    baseline = outcomes["original"]
    detected = [
        fault
        for fault in FAULTS
        if any(value == "pass" and outcomes[fault].get(case) == "fail" for case, value in baseline.items())
    ]
    report = {
        "baseline_only": True,
        "outcomes": outcomes,
        "faults_detected": detected,
        "note": "Traditional fixed assertions only. This is not a comparison with LLM-generated or manual MRs.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if baseline and set(baseline.values()) == {"pass"} and len(detected) == len(FAULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
