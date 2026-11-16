"""Fault-revealing rules: discard MRs that cannot fail whatever the SUT does.

They catch tautologies (the follow-up is the same request as the source) and
relations whose measure is constant. Anything subtler is left to the LLM check.
"""

from __future__ import annotations

from app.models.mr import Measure, MRNotExecutableError, MRSpec, RelationType, RequestSpec
from app.pipeline.context_extractor import ApiContext
from app.pipeline.filters.semantic import MAX_VIOLATIONS, field_type

# With an identical follow-up these relations still check something useful: determinism.
DETERMINISM_RELATIONS = {RelationType.EQUALITY, RelationType.EQUIVALENCE}


def _same_request(a: RequestSpec, b: RequestSpec) -> bool:
    return (a.method, a.path, a.path_params, a.query_params) == (b.method, b.path, b.path_params, b.query_params)


def fault_violations(spec: MRSpec, ctx: ApiContext) -> list[str]:
    try:
        instances = spec.instances()
    except MRNotExecutableError as exc:
        return [f"no se pueden derivar las peticiones: {exc}"]

    relation = spec.relation
    found: dict[str, None] = {}
    same_selector = relation.source_selector == relation.effective_followup_selector
    if relation.type not in DETERMINISM_RELATIONS and same_selector:
        for source, followups in instances:
            for i, followup in enumerate(followups, 1):
                if _same_request(source, followup):
                    found[
                        f"el follow-up {i} es idéntico a la fuente: la transformación no cambia nada y la relación "
                        f"{relation.type.value} no puede revelar un fallo"
                    ] = None

    if relation.type is RelationType.COUNT_LEQ and relation.measure is Measure.COUNT:
        op = ctx.find_operation(spec.source.method.value, spec.source.path)
        kind = field_type(relation.source_selector, op) if op else None
        if kind and "[*]" not in relation.source_selector and not kind.startswith("array"):
            found[
                f"contar '{relation.source_selector}' siempre da 1 porque es un único valor: "
                "la relación count_leq es trivial (¿faltó measure=value?)"
            ] = None
    return list(found)[:MAX_VIOLATIONS]
