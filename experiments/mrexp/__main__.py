"""MetaREST experiments CLI.  Run from ``experiments/``:  ``python -m mrexp <command> --help``.

    run          one MetaREST run with the frozen settings of config/experiment.json (calls the real LLM)
    label-sheet  blind CSV of every candidate for manual validity labeling (RQ1)
    rq1          validity before/after the filter + Cohen's kappa, from the filled sheet
    rq2          redundancy before/after the diversity filter (+ unique detections of redundant MRs)
    coverage     operations / parameters of the spec exercised by the MRs
    mutants      detection matrix on the demo API's fault variants (RQ3)
    calibrate    compare verification models / thresholds on execution-labeled MRs (calls the real LLM)

CSVs go to experiments/results/ (versioned); raw execution evidence to experiments/raw/ (git-ignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from mrexp.io import load_manual_mrs, load_runs, read_csv, select_candidates, write_csv
from mrexp.metrics import (
    SHEET_COLUMNS,
    coverage_rows,
    join_labels,
    label_sheet_rows,
    redundant_unique_detection_rows,
    rq1_by_stage_rows,
    rq1_rows,
    rq2_rows,
)
from mrexp.mutants import (
    ORIGINAL,
    Item,
    Outcomes,
    default_client_factory,
    detection_rows,
    fault_matrix_rows,
    mr_items,
    run_mrs,
    run_pytest_suite,
    served,
    summary_rows,
    tests_to_outcomes,
    verdicts_to_outcomes,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RAW = ROOT / "raw"


def _out(args: argparse.Namespace, suffix: str) -> Path:
    return args.out_dir / f"{args.name}_{suffix}.csv"


def _print_rows(rows: list[dict[str, Any]], columns: list[str]) -> None:
    for row in rows:
        print("  " + " · ".join(f"{c}={_fmt(row.get(c))}" for c in columns))


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if value is None:
        return "—"
    return str(value)


# ───────────────────────────── commands ─────────────────────────────


async def cmd_run(args: argparse.Namespace) -> None:
    from app.pipeline.embeddings import FastEmbedEmbedder
    from app.pipeline.llm import create_provider
    from scripts._env import load_env

    from mrexp import runs
    from mrexp.suts import PRESETS, SUTPreset

    if args.name == "exp":
        raise SystemExit("usa --name <api>_run<n> (p. ej. --name pokeapi_run1): es el id del run en las tablas")
    if args.sut in PRESETS:
        preset = PRESETS[args.sut]
    elif args.spec and args.base_url:
        preset = SUTPreset(args.spec, args.base_url, args.max_concurrency, args.min_interval, args.timeout)
    else:
        raise SystemExit(f"SUT desconocida {args.sut!r}: usa {', '.join(PRESETS)} o pasa --spec y --base-url")
    out = args.raw_dir / f"{args.name}.json"
    if out.exists() and not args.force:
        raise SystemExit(f"{out} ya existe (es un run de experimento: no se sobrescribe sin --force)")

    loaded = load_env()
    if loaded:
        print(f"variables cargadas de backend/.env: {', '.join(loaded)}")
    settings = runs.load_settings(args.config)
    llm, filters = settings.llm, settings.filters
    print(f"· {args.name}: {args.sut} ({preset.base_url}) · {args.config.name}")
    print(
        f"  generación {llm.generation_model} ({llm.generation_effort}) · verificación {llm.verification_model} "
        f"({llm.verification_effort}) · {llm.max_candidates} MRs · prompts {settings.generation_prompt}, "
        f"{filters.semantic_prompt}, {filters.fault_prompt}"
    )

    async def show(report) -> None:
        running = [s.name.value for s in report.stages if s.status.value == "running"]
        if running:
            print(f"  … {running[0]}", flush=True)

    result, payload = await runs.execute_run(
        args.name,
        args.sut,
        preset,
        settings,
        create_provider(llm),
        FastEmbedEmbedder(filters.embedding_model, cache_dir=str(args.cache_dir)),
        config_path=args.config,
        on_progress=show,
    )
    for st in result.report.stages:
        print(
            f"  {st.name.value:<16} {st.status.value:<8} {st.input_count or 0:>3} → {st.output_count or 0:>3}  "
            f"{(st.duration_ms or 0) / 1000:>6.1f} s {st.usage.total:>7} tok  {st.detail or ''}"
        )
    print(f"  conteos: {result.counts} · tokens: {result.report.usage.total}")
    problems = payload["meta"]["problems"]
    if problems:
        failed = out.with_suffix(".failed.json")
        runs.write_export(payload, failed)
        print("NO USAR para los experimentos (repite el run):")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(f"→ {failed}")
    if payload["meta"]["git"]["pipeline_dirty"]:
        print("OJO: backend/app o experiments/config tienen cambios sin commit; el run no es reproducible por commit")
    runs.write_export(payload, out)
    print(f"→ {out}")


def cmd_label_sheet(args: argparse.Namespace) -> None:
    rows = label_sheet_rows(load_runs(args.runs), seed=args.seed)
    path = write_csv(args.out or _out(args, "labels"), rows, SHEET_COLUMNS)
    print(f"{len(rows)} candidatas → {path}")
    print("Cada etiquetador llena su columna (label_a / label_b) con 1 = válida, 0 = inválida, sin ver la del otro.")


def _warn_failed_checks(runs) -> None:
    for run in runs:
        failed = [w for w in run.report.get("warnings", []) if "chequeo" in w.lower()]
        if failed:
            print(f"OJO: {run.label} tuvo chequeos LLM fallidos (puntuados solo con reglas); repetir el run para RQ1:")
            for w in failed:
                print(f"  - {w}")


def cmd_rq1(args: argparse.Namespace) -> None:
    runs = load_runs(args.runs)
    _warn_failed_checks(runs)
    labeled = join_labels(runs, read_csv(args.labels))
    groups = [("all", labeled)]
    if len(runs) > 1:
        for r in runs:
            ids = {id(c) for c in r.candidates}
            groups.append((r.label, [x for x in labeled if id(x.candidate) in ids]))
    rows = [rq1_rows(items, name) for name, items in groups]
    stages = rq1_by_stage_rows(labeled)
    write_csv(_out(args, "rq1"), rows)
    write_csv(_out(args, "rq1_by_stage"), stages)
    _print_rows(rows, ["group", "labeled", "kappa", "valid_rate_pre", "valid_rate_post", "filter_precision"])
    _print_rows(stages, ["outcome", "candidates", "labeled_valid", "labeled_invalid"])
    print(f"→ {_out(args, 'rq1')}, {_out(args, 'rq1_by_stage')}")


def _embedder(args: argparse.Namespace):
    if args.embedder == "hashing":
        from app.pipeline.embeddings import HashingEmbedder

        return HashingEmbedder()
    from app.pipeline.embeddings import FastEmbedEmbedder

    return FastEmbedEmbedder(args.embedding_model, cache_dir=str(args.cache_dir))


async def cmd_rq2(args: argparse.Namespace) -> None:
    summary, clusters = await rq2_rows(load_runs(args.runs), _embedder(args), args.threshold or None)
    write_csv(_out(args, "rq2"), summary)
    write_csv(_out(args, "rq2_clusters"), clusters)
    _print_rows(summary, ["run", "threshold", "set", "mrs", "clusters", "redundancy_rate"])
    outputs = [_out(args, "rq2"), _out(args, "rq2_clusters")]
    if args.detections:
        unique = redundant_unique_detection_rows(read_csv(args.detections))
        write_csv(_out(args, "rq2_redundant_detections"), unique)
        _print_rows(unique, ["fault", "detected_by_selected", "detected_by_redundant", "only_redundant_detect"])
        outputs.append(_out(args, "rq2_redundant_detections"))
    print("→ " + ", ".join(map(str, outputs)))


def cmd_coverage(args: argparse.Namespace) -> None:
    from app.pipeline.context_extractor import extract_context

    context = extract_context(args.spec.read_text(encoding="utf-8"))
    runs = load_runs(args.runs)
    groups = {
        "metarest_generated": [m.spec for m in select_candidates(runs, "all")],
        "metarest_selected": [m.spec for m in select_candidates(runs, "passed")],
    }
    accepted = [m.spec for m in select_candidates(runs, "accepted")]
    if accepted:
        groups["metarest_accepted"] = accepted
    if args.manual:
        groups["manual"] = [m.spec for m in load_manual_mrs(args.manual)]
    summary, uncovered = coverage_rows(context, groups)
    write_csv(_out(args, "coverage"), summary)
    write_csv(_out(args, "coverage_uncovered"), uncovered, ["group", "kind", "method", "path", "param"])
    _print_rows(summary, ["group", "mrs", "ops_covered", "ops_total", "params_covered", "params_total"])
    print(f"→ {_out(args, 'coverage')}, {_out(args, 'coverage_uncovered')}")


def _variants(args: argparse.Namespace) -> list[tuple[str, str | None]]:
    """[(variant name, base URL or None when served)], original first."""
    if args.serve:
        faults = [f.strip() for f in args.faults.split(",") if f.strip()]
        return [(ORIGINAL, None), *((f, None) for f in faults)]
    pairs = []
    for spec in args.variant:
        name, sep, url = spec.partition("=")
        if not sep or not url:
            raise SystemExit(f"--variant {spec!r}: usa nombre=URL")
        pairs.append((name.strip(), url.strip()))
    if ORIGINAL not in (n for n, _ in pairs):
        raise SystemExit("falta --variant original=URL (la API sin fallos)")
    return sorted(pairs, key=lambda p: p[0] != ORIGINAL)


async def cmd_mutants(args: argparse.Namespace) -> None:
    if bool(args.serve) == bool(args.variant):
        raise SystemExit("usa --variant nombre=URL (servidores ya levantados) o --serve CMD --faults ... (no ambos)")
    if args.serve and not args.faults:
        raise SystemExit("--serve requiere --faults a,b,c")
    mrs = select_candidates(load_runs(args.run), args.select) if args.run else []
    if args.manual:
        mrs += load_manual_mrs(args.manual)
    if not mrs and not args.tests:
        raise SystemExit("nada que ejecutar: pasa --run, --manual y/o --tests")

    variants = _variants(args)
    faults = [name for name, _ in variants if name != ORIGINAL]
    factory = default_client_factory(timeout=args.timeout, max_concurrency=args.concurrency)
    executions: dict[str, dict[str, dict[str, Any]]] = {}  # technique -> variant -> id -> result
    tests: dict[str, dict[str, str]] = {}
    for i, (variant, url) in enumerate(variants):
        fault = None if variant == ORIGINAL else variant
        context = (
            served(args.serve, fault, port=args.port + i, health_path=args.health, cwd=args.serve_cwd)
            if args.serve
            else nullcontext(url)
        )
        with context as base_url:
            print(f"· {variant} ({base_url})")
            for technique in ("manual", "metarest"):
                group = [m for m in mrs if m.technique == technique]
                if group:
                    results = await run_mrs(group, variant, base_url, factory, concurrency=args.concurrency)
                    executions.setdefault(technique, {})[variant] = results
            if args.tests:
                tests[variant] = await asyncio.to_thread(
                    run_pytest_suite, args.tests, base_url, pytest_cmd=args.pytest_cmd, env_var=args.tests_env
                )

    outcomes: Outcomes = {}
    items: list[Item] = []
    if tests:
        items += tests_to_outcomes(tests, outcomes)
    for technique, per_variant in executions.items():
        verdicts_to_outcomes(technique, per_variant, outcomes)
    items += mr_items(mrs)

    rows = detection_rows(items, outcomes, faults, strict=args.strict)
    summary = summary_rows(items, outcomes, faults, strict=args.strict)
    matrix = fault_matrix_rows(items, outcomes, faults, strict=args.strict)
    write_csv(_out(args, "detections"), rows)
    write_csv(_out(args, "rq3_summary"), summary)
    write_csv(_out(args, "rq3_fault_matrix"), matrix)
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    raw = args.raw_dir / f"{args.name}_mutants.json"
    evidence = {
        t: {v: {i: r.model_dump(mode="json") for i, r in res.items()} for v, res in pv.items()}
        for t, pv in executions.items()
    }
    raw.write_text(json.dumps({"mrs": evidence, "tests": tests}, ensure_ascii=False, indent=1), encoding="utf-8")

    _print_rows(summary, ["combination", "items", "items_not_passing_original", "faults_detected", "faults_total"])
    print(f"→ {_out(args, 'detections')}, {_out(args, 'rq3_summary')}, {_out(args, 'rq3_fault_matrix')}")
    print(f"evidencia HTTP → {raw}")


async def cmd_calibrate(args: argparse.Namespace) -> None:
    from app.pipeline.context_extractor import extract_context
    from app.pipeline.llm import LLMSettings, create_provider
    from scripts._env import load_env

    from mrexp import calibration as cal

    load_env()
    items: list[cal.CalibrationItem] = []
    contexts = {}
    for case_arg in args.case:
        case, _, run_path = case_arg.partition("=")
        preset = cal.PRESETS[case]
        contexts[case] = extract_context(preset.spec.read_text(encoding="utf-8"))
        case_items = cal.build_items(case, load_runs([Path(run_path)])[0], contexts[case])
        async with preset.client() as client:
            await cal.execute_items(case_items, client, concurrency=preset.max_concurrency)
        labels = [i.label for i in case_items]
        print(f"· {case}: " + ", ".join(f"{k}={labels.count(k)}" for k in ("valid", "invalid", "uncertain", "rules")))
        items += case_items

    configs = [cal.CheckConfig.parse(c) for c in args.config]
    for config in configs:
        provider = create_provider(LLMSettings(provider=args.provider, timeout_seconds=args.llm_timeout))
        print(f"· chequeos con {config.name} …")
        await cal.run_checks(items, contexts, provider, config, concurrency=args.llm_concurrency)

    names = [c.name for c in configs]
    summary = cal.summary_rows(items, names)
    write_csv(_out(args, "calibration"), summary)
    write_csv(_out(args, "calibration_items"), cal.item_rows(items, names))
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    raw = args.raw_dir / f"{args.name}_calibration.json"
    dump = [
        {
            **{k: getattr(i, k) for k in ("case", "id", "kind", "operator", "verdict", "rule_violations", "checks")},
            "label": i.label,
            "spec": i.spec.model_dump(mode="json"),
        }
        for i in items
    ]
    raw.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    _print_rows(summary, ["config", "valid", "invalid", "errors", "sem_auc", "sem_mean_valid", "sem_mean_invalid"])
    print(f"→ {_out(args, 'calibration')}, {_out(args, 'calibration_items')}, {raw}")


# ───────────────────────────── parser ─────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mrexp", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--name", default="exp", help="prefix of the output files (e.g. demo, pokeapi)")
    common.add_argument("--out-dir", type=Path, default=RESULTS)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", parents=[common], help="one MetaREST run with the frozen settings (real LLM)")
    p.add_argument("sut", help="pokeapi | crossref | any name with --spec and --base-url (e.g. demo)")
    p.add_argument("--config", type=Path, default=ROOT / "config" / "experiment.json")
    p.add_argument("--spec", type=Path, help="OpenAPI file (SUTs without preset)")
    p.add_argument("--base-url")
    p.add_argument("--max-concurrency", type=int, default=4)
    p.add_argument("--min-interval", type=float, default=0.0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--cache-dir", type=Path, default=ROOT.parent / ".fastembed_cache")
    p.add_argument("--raw-dir", type=Path, default=RAW)
    p.add_argument("--force", action="store_true", help="overwrite an existing run export")

    p = sub.add_parser("label-sheet", parents=[common], help="blind labeling sheet (RQ1)")
    p.add_argument("runs", nargs="+", type=Path, help="run exports (JSON with settings/report/candidates)")
    p.add_argument("--seed", type=int, default=13)
    p.add_argument("--out", type=Path)

    p = sub.add_parser("rq1", parents=[common], help="validity pre/post filter + kappa")
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--labels", type=Path, required=True, help="the filled label sheet")

    p = sub.add_parser("rq2", parents=[common], help="redundancy pre/post diversity")
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--threshold", type=float, action="append", help="repeatable; default: the run's threshold")
    p.add_argument("--detections", type=Path, help="detections CSV of `mutants --select all`")
    p.add_argument("--embedder", choices=["fastembed", "hashing"], default="fastembed")
    p.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    p.add_argument("--cache-dir", type=Path, default=ROOT.parent / ".fastembed_cache")

    p = sub.add_parser("coverage", parents=[common], help="operations / parameters exercised")
    p.add_argument("spec", type=Path, help="OpenAPI file of the SUT")
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--manual", type=Path, help="directory with the manual MRs (JSON)")

    p = sub.add_parser("mutants", parents=[common], help="fault detection matrix (RQ3)")
    p.add_argument("--run", nargs="*", type=Path, default=[], help="MetaREST run exports")
    p.add_argument(
        "--select", choices=["accepted", "passed", "all"], default="passed", help="which MetaREST MRs (default passed)"
    )
    p.add_argument("--manual", type=Path, help="directory with the manual MRs (JSON)")
    p.add_argument("--tests", type=Path, help="traditional pytest suite (reads the SUT URL from --tests-env)")
    p.add_argument("--tests-env", default="SUT_BASE_URL")
    p.add_argument("--pytest-cmd", help='default: "<this python> -m pytest"')
    p.add_argument("--variant", action="append", default=[], help="name=URL, repeatable; one must be original")
    p.add_argument("--serve", help='start each variant: command with {port}, e.g. "uvicorn app.main:app --port {port}"')
    p.add_argument("--faults", help="comma-separated faults for --serve (passed as FAULTS=<fault>)")
    p.add_argument("--serve-cwd", type=Path)
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--health", default="/health")
    p.add_argument("--strict", action="store_true", help="only violation/fail count as detection (not error)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--raw-dir", type=Path, default=RAW, help="where the HTTP evidence JSON goes (git-ignored)")

    p = sub.add_parser("calibrate", parents=[common], help="verification model / threshold calibration (real LLM)")
    p.add_argument("--case", action="append", required=True, help="preset=run.json, e.g. pokeapi=raw/smoke.json")
    p.add_argument("--config", action="append", required=True, help="model:effort, e.g. gemini-4-hydrogen:low")
    p.add_argument("--provider", choices=["gemini", "anthropic"], default="gemini")
    p.add_argument("--llm-concurrency", type=int, default=4)
    p.add_argument("--llm-timeout", type=float, default=120.0)
    p.add_argument("--raw-dir", type=Path, default=RAW)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    match args.command:
        case "run":
            asyncio.run(cmd_run(args))
        case "label-sheet":
            cmd_label_sheet(args)
        case "rq1":
            cmd_rq1(args)
        case "rq2":
            asyncio.run(cmd_rq2(args))
        case "coverage":
            cmd_coverage(args)
        case "mutants":
            asyncio.run(cmd_mutants(args))
        case "calibrate":
            asyncio.run(cmd_calibrate(args))


if __name__ == "__main__":
    main()
