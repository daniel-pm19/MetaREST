"""Manual smoke test with the REAL LLM (costs tokens; never run in CI).

Generates MRs for an OpenAPI spec and, optionally, executes them against a SUT.

    cd backend
    # reads ANTHROPIC_API_KEY from backend/.env (or from the shell)
    python -m scripts.smoke_generate tests/fixtures/openapi_search.yaml -n 5
    python -m scripts.smoke_generate path/to/spec.yaml -n 5 --base-url http://localhost:8001

Output: a summary on stdout and the full result as JSON in --out
(default: ../experiments/raw/smoke_result.json, which is git-ignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.pipeline.context_extractor import extract_context
from app.pipeline.executor import SUTClient, execute_many
from app.pipeline.generator import generate_relations
from app.pipeline.llm import LLMSettings, create_provider
from scripts._env import load_env


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path)
    parser.add_argument("-n", type=int, default=5, help="relations to request (default 5)")
    parser.add_argument("--provider", choices=["anthropic", "gemini"], default="anthropic")
    parser.add_argument("--model", help="generation model (default: the provider's default)")
    parser.add_argument("--effort", default=LLMSettings().generation_effort)
    parser.add_argument("--base-url", help="if given, execute the valid MRs against this SUT")
    parser.add_argument("--min-interval", type=float, default=0.0, help="seconds between SUT requests (Crossref: 1)")
    parser.add_argument("--max-concurrency", type=int, default=4, help="parallel SUT requests (Crossref: 1)")
    parser.add_argument("--timeout", type=float, default=10.0, help="SUT request timeout in seconds (Crossref: 30)")
    parser.add_argument("--no-fallbacks", action="store_true", help="disable server-side refusal fallbacks")
    parser.add_argument("--out", type=Path, default=Path("../experiments/raw/smoke_result.json"))
    args = parser.parse_args()
    loaded = load_env()
    if loaded:
        print(f"variables cargadas de backend/.env: {', '.join(loaded)}")

    context = extract_context(args.spec.read_text(encoding="utf-8"))
    print(f"API: {context.title} — {len(context.operations)} operaciones GET/HEAD")
    settings = LLMSettings(provider=args.provider, enable_fallbacks=not args.no_fallbacks)
    provider = create_provider(settings)
    model = args.model or settings.generation_model
    result = await generate_relations(context, provider, model=model, n=args.n, effort=args.effort)

    print(f"modelo: {result.model} (fallback: {result.fallback_used}) · prompt: {result.prompt_id}")
    print(f"tokens: entrada {result.usage.input_tokens}, salida {result.usage.output_tokens}")
    if result.error:
        print(f"ERROR: {result.error}")
    for w in result.warnings:
        print(f"aviso: {w}")
    print(f"válidas: {len(result.specs)} · no ejecutables: {len(result.rejected)}")
    for item, err in result.rejected:
        print(f"  ✗ {str(item)[:80]}… → {err[:200]}")

    executions = []
    if args.base_url and result.specs:
        async with SUTClient(
            args.base_url, min_interval=args.min_interval, max_concurrency=args.max_concurrency, timeout=args.timeout
        ) as client:
            executions = await execute_many(result.specs, client)
    for i, spec in enumerate(result.specs):
        verdict = f" → {executions[i].verdict.value}" if executions else ""
        print(f"  ✓ [{spec.relation.type.value}] {spec.title}{verdict}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "model": result.model,
                "prompt_id": result.prompt_id,
                "usage": result.usage.model_dump(),
                "error": result.error,
                "warnings": result.warnings,
                "specs": [s.model_dump(mode="json") for s in result.specs],
                "rejected": [{"item": item, "error": err} for item, err in result.rejected],
                "executions": [e.model_dump(mode="json") for e in executions],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"resultado completo en {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
