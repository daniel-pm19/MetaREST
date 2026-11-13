from __future__ import annotations

import pytest

from app.models.mr import RelationSpec
from app.pipeline.executor.relations import RelationEvaluationError, evaluate
from app.pipeline.executor.selectors import SelectorError, select


def rel(type_: str, **kw) -> RelationSpec:
    return RelationSpec(type=type_, **kw)


# ─────────────────────────── selectors ───────────────────────────

BODY = {"total": 3, "results": [{"id": 1, "tags": ["a"]}, {"id": 2, "tags": []}], "empty": []}


def test_select_values():
    assert select(BODY, "$.results[*].id") == [1, 2]
    assert select(BODY, "$.total") == [3]
    assert select(BODY, "$.results[?(@.id > 1)].id") == [2]  # extended filter syntax
    assert select([{"id": 5}], "$[*].id") == [5]


def test_empty_array_is_a_valid_empty_selection():
    assert select({"results": []}, "$.results[*].id") == []
    assert select(BODY, "$.empty[*]") == []


@pytest.mark.parametrize("expr", ["$.missing", "$.nope[*].id", "$.total[*]"])
def test_missing_fields_are_errors(expr):
    with pytest.raises(SelectorError, match="no encontró"):
        select(BODY, expr)


def test_invalid_expression_and_missing_body():
    with pytest.raises(SelectorError, match="inválido"):
        select(BODY, "$.results[")
    with pytest.raises(SelectorError, match="cuerpo"):
        select(None, "$")


# ─────────────────────────── relations ───────────────────────────


@pytest.mark.parametrize(
    "relation, source, followups, holds",
    [
        (rel("equality"), [1, 2, 3], [[1, 2, 3]], True),
        (rel("equality"), [1, 2, 3], [[1, 3, 2]], False),
        (rel("equivalence"), [1, 2, 2], [[2, 1, 2]], True),
        (rel("equivalence"), [1, 2, 2], [[2, 1]], False),  # multiset, not set
        (rel("subset", direction="followup_in_source"), [1, 2, 3], [[3, 1]], True),
        (rel("subset", direction="followup_in_source"), [1, 2, 3], [[3, 9]], False),
        (rel("subset", direction="source_in_followup"), [1], [[1, 2]], True),
        (rel("subset", direction="source_in_followup"), [1, 7], [[1, 2]], False),
        (rel("disjoint"), [1, 2], [[3, 4], [5]], True),
        (rel("disjoint"), [1, 2], [[3, 4], [4]], False),  # follow-ups must also be disjoint
        (rel("complete"), [1, 2, 3, 4], [[1, 2], [3, 4]], True),
        (rel("complete"), [1, 2, 3, 4], [[1, 2], [4]], False),
        (rel("complete"), [1, 2], [[1, 2], [3]], False),  # extra element
        (rel("difference"), [1, 2, 3, 4], [[1, 2], [3, 4]], True),
        (rel("difference"), [1, 2, 3, 4], [[1, 2], [3]], False),
        (rel("count_leq", direction="followup_in_source"), [1, 2, 3], [[1], [1, 2, 3]], True),
        (rel("count_leq", direction="followup_in_source"), [1], [[1, 2]], False),
        (rel("count_leq", direction="source_in_followup"), [1], [[1, 2]], True),
        (rel("count_leq", direction="followup_in_source", measure="value"), [57], [[12]], True),
        (rel("count_leq", direction="followup_in_source", measure="value"), [12], [[57.5]], False),
        (rel("same_order"), [1, 2, 3, 4], [[1, 9, 3, 4]], True),  # common elements keep order
        (rel("same_order"), [1, 2, 3, 4], [[3, 1]], False),
        (rel("same_order"), [1, 2], [[5, 6]], True),  # nothing in common
    ],
)
def test_relation_catalog(relation, source, followups, holds):
    check = evaluate(relation, source, followups)
    assert check.holds is holds, check.message
    assert check.message


def test_objects_are_compared_regardless_of_key_order():
    check = evaluate(rel("equality"), [{"a": 1, "b": 2}], [[{"b": 2, "a": 1}]])
    assert check.holds


def test_violation_messages_are_informative():
    msg = evaluate(rel("subset", direction="followup_in_source"), [1, 2], [[1, 87, 91]]).message
    assert "87" in msg and "91" in msg and "(2)" in msg
    msg = evaluate(rel("complete"), [1, 2, 3], [[1], [2]]).message
    assert "faltan [3]" in msg


@pytest.mark.parametrize("values", [[1, 2], ["57"], [True], []])
def test_measure_value_needs_a_single_number(values):
    with pytest.raises(RelationEvaluationError, match="único número"):
        evaluate(rel("count_leq", direction="followup_in_source", measure="value"), values, [[1]])


def test_difference_needs_two_followups_and_any_relation_needs_one():
    with pytest.raises(RelationEvaluationError):
        evaluate(rel("difference"), [1], [[1]])
    with pytest.raises(RelationEvaluationError):
        evaluate(rel("equality"), [1], [])
