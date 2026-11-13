"""Manual smoke test of the WHOLE pipeline with the real LLM (costs tokens; never run in CI).

Generation + filters (Haiku checks, local embeddings) + optional execution against a SUT.
The first run downloads the embedding model (~70 MB) into --cache-dir.

    cd backend
    python -m scripts.smoke_pipeline tests/fixtures/openapi_search.yaml -n 8
    python -m scripts.smoke_pipeline path/to/spec.yaml -n 8 --base-url http://localhost:8001

Output: a summary on stdout and every candidate + the run report as JSON in --out
(default: ../experiments/raw/smoke_pipeline.json, which is git-ignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from pathlib import Path

from app.pipeline.embeddings import FastEmbedEmbedder
from app.pipeline.executor import SUTClient
from app.pipeline.filters import FilterSettings
from app.pipeline.llm import LLMSettings, create_provider
from app.pipeline.orchestrator import PipelineSettings, run_pipeline
from scripts._env import load_env


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path)
    parser.add_argument("-n", type=int, default=8, help="MRs to request (default 8)")
    parser.add_argument("--base-url", help="execute the surviving MRs against this SUT")
    parser.add_argument("--no-llm-checks", action="store_true", help="filter with rules only")
    parser.add_argument("--no-fallbacks", action="store_true")
    parser.add_argument("--cache-dir", default="../.fastembed_cache", help="where the embedding model is stored")
    parser.add_argument("--out", type=Path, default=Path("../experiments/raw/smoke_pipeline.json"))
    args = parser.parse_args()
    loaded = load_env()
    if loaded:
        print(f"variables cargadas de backend/.env: {', '.join(loaded)}")

    llm = LLMSettings(max_candidates=args.n, enable_fallbacks=not args.no_fallbacks)
    filters = FilterSettings(use_llm_checks=not args.no_llm_checks)
    settings = PipelineSettings(llm=llm, filters=filters)

    async def show(report) -> None:
        running = [s.name.value for s in report.stages if s.status.value == "running"]
        if running:
            print(f"… {running[0]}")

    async with AsyncExitStack() as stack:
        sut = await stack.enter_async_context(SUTClient(args.base_url)) if args.base_url else None
        result = await run_pipeline(
            args.spec.read_text(encoding="utf-8"),
            project_id="smoke",
            run_id="smoke",
            provider=create_provider(llm),
            embedder=FastEmbedEmbedder(filters.embedding_model, cache_dir=args.cache_dir),
            sut=sut,
            settings=settings,
            on_progress=show,
        )

    report = result.report
    print(f"\nerror: {report.error}" if report.error else "\nrun OK")
    for s in report.stages:
        timing = f"{s.duration_ms or 0:>8.0f} ms  {s.usage.total:>7} tok"
        print(f"  {s.name.value:<16} {s.status.value:<8} {timing}  {s.detail}")
    for w in report.warnings:
        print(f"aviso: {w}")
    print(f"tokens totales: {report.usage.total} · conteos: {result.counts}")
    for c in result.candidates:
        title = c.spec.title if c.spec else str(c.raw_output)[:60]
        fr = c.filter_result
        tag = "✓ pendiente" if fr and fr.passed else f"✗ {fr.reason.value if fr and fr.reason else '?'}"
        verdict = f" → {c.execution.verdict.value}" if c.execution else ""
        combined = f" [{c.scores.combined:.2f}]" if c.scores.combined is not None else ""
        print(f"  {tag:<24}{combined} {title}{verdict}")
        if fr and not fr.passed and fr.detail:
            print(f"      {fr.detail[:160]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "settings": settings.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
        "candidates": [c.model_dump(mode="json") for c in result.candidates],
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"resultado completo en {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
