"""Execute MRs against the SUT and produce verdicts with HTTP evidence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from app.models.mr import ExecutionResult, HttpExchange, InstanceExecution, MRSpec, RequestSpec, Verdict
from app.pipeline.executor.http import FetchResult, SUTClient
from app.pipeline.executor.relations import RelationEvaluationError, evaluate
from app.pipeline.executor.selectors import SelectorError, select

SELECTED_LIMIT = 2000


def _selected_excerpt(values: list[Any]) -> str:
    text = json.dumps(values, ensure_ascii=False)
    return text if len(text) <= SELECTED_LIMIT else text[: SELECTED_LIMIT - 1] + "…"


def _failure_message(role: str, result: FetchResult) -> str:
    ex = result.exchange
    if ex.error:
        return f"{role}: {ex.error}"
    return f"{role}: respuesta HTTP {ex.status_code} (se esperaba 2xx)"


async def execute_instance(
    index: int, source: RequestSpec, followups: list[RequestSpec], spec: MRSpec, client: SUTClient
) -> InstanceExecution:
    results = await asyncio.gather(client.fetch(source), *(client.fetch(f) for f in followups))
    n_followups = len(results) - 1
    roles = ["fuente", *(f"follow-up {i + 1}" for i in range(n_followups))]

    def instance(verdict: Verdict, message: str, exchanges: list[HttpExchange] | None = None) -> InstanceExecution:
        exs = exchanges or [r.exchange for r in results]
        return InstanceExecution(index=index, source=exs[0], followups=exs[1:], verdict=verdict, message=message[:1000])

    for role, result in zip(roles, results, strict=True):
        if not result.ok:
            return instance(Verdict.ERROR, _failure_message(role, result))

    relation = spec.relation
    exchanges: list[HttpExchange] = []
    selections: list[list[Any]] = []
    try:
        for role, result, expr in zip(
            roles,
            results,
            [relation.source_selector, *([relation.effective_followup_selector] * n_followups)],
            strict=True,
        ):
            try:
                values = select(result.body, expr)
            except SelectorError as exc:
                raise SelectorError(f"{role}: {exc}") from exc
            selections.append(values)
            exchanges.append(result.exchange.model_copy(update={"selected_excerpt": _selected_excerpt(values)}))
        check = evaluate(relation, selections[0], selections[1:])
    except (SelectorError, RelationEvaluationError) as exc:
        return instance(Verdict.ERROR, str(exc), exchanges + [r.exchange for r in results[len(exchanges) :]])

    message = check.message
    if check.holds and all(not s for s in selections):
        message += " (todas las selecciones están vacías: evidencia débil)"
    return instance(Verdict.PASS if check.holds else Verdict.VIOLATION, message, exchanges)


async def execute_mr(spec: MRSpec, client: SUTClient) -> ExecutionResult:
    """Run every input instance of the MR (base + variants) and aggregate the verdict."""
    instances = [
        await execute_instance(i, src, fus, spec, client)  # sequential: keeps SUT load predictable
        for i, (src, fus) in enumerate(spec.instances())
    ]
    return ExecutionResult(verdict=ExecutionResult.aggregate(x.verdict for x in instances), instances=instances)


async def execute_many(specs: Sequence[MRSpec], client: SUTClient, concurrency: int = 4) -> list[ExecutionResult]:
    """Execute several MRs with bounded parallelism; results keep the input order."""
    sem = asyncio.Semaphore(concurrency)

    async def run(spec: MRSpec) -> ExecutionResult:
        async with sem:
            return await execute_mr(spec, client)

    return list(await asyncio.gather(*(run(s) for s in specs)))
