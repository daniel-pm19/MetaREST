"""Tests for the executable MR contract (app/models/mr.py) and docs/mr_examples/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.mr import (
    CandidateStatus,
    DiscardReason,
    ExecutionResult,
    FilterOutcome,
    FilterStage,
    MRCandidate,
    MRSpec,
    RequestSpec,
    Verdict,
    json_schemas,
    parse_generated_relations,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "mr_examples"
SPEC_EXAMPLES = sorted((EXAMPLES / "specs").glob("*.json"))
CANDIDATE_EXAMPLES = sorted((EXAMPLES / "candidates").glob("*.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def spec(**overrides) -> dict:
    base = {
        "title": "Subset on limit",
        "description": "Lower limit returns a subset.",
        "source": {"path": "/search", "query_params": {"q": "jazz", "limit": 20}},
        "followups": [{"transformations": [{"op": "set_param", "param": "limit", "value": 10}]}],
        "relation": {"type": "subset", "source_selector": "$.results[*].id", "direction": "followup_in_source"},
        "transformation_logic": "limit 20 -> 10",
        "expected_relation": "F ⊆ S",
        "rationale": "Catches ignored limit.",
    }
    base.update(overrides)
    return base


def followup_of(mr: MRSpec, i: int = 0, instance: int = 0) -> RequestSpec:
    return mr.instances()[instance][1][i]


# ─────────────────────────── examples ────────────────────────────


def test_examples_exist():
    assert len(SPEC_EXAMPLES) >= 3
    assert len(CANDIDATE_EXAMPLES) >= 3


@pytest.mark.parametrize("path", SPEC_EXAMPLES, ids=lambda p: p.name)
def test_spec_examples_are_valid(path: Path):
    MRSpec.model_validate(load(path))


@pytest.mark.parametrize("path", CANDIDATE_EXAMPLES, ids=lambda p: p.name)
def test_candidate_examples_are_valid(path: Path):
    MRCandidate.model_validate(load(path))


def test_subset_example_instances():
    mr = MRSpec.model_validate(load(EXAMPLES / "specs" / "01_subset_limit.json"))
    pairs = mr.instances()
    assert len(pairs) == 3  # base + 2 input variants
    assert [src.query_params for src, _ in pairs] == [
        {"q": "jazz", "limit": 20},
        {"q": "rock", "limit": 20},
        {"q": "blues", "limit": 8},
    ]
    assert [fus[0].query_params["limit"] for _, fus in pairs] == [10, 10, 4]


# ───────────────────────── requests ──────────────────────────────


def test_only_safe_methods():
    with pytest.raises(ValidationError):
        RequestSpec(method="DELETE", path="/items/{id}", path_params={"id": 1})
    with pytest.raises(ValidationError):
        MRSpec.model_validate(spec(followups=[{"method": "POST"}]))


def test_path_params_must_match_placeholders():
    RequestSpec(path="/items/{id}", path_params={"id": 3})
    with pytest.raises(ValidationError, match="missing"):
        RequestSpec(path="/items/{id}")
    with pytest.raises(ValidationError, match="not placeholders"):
        RequestSpec(path="/items", path_params={"id": 3})


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        MRSpec.model_validate(spec(extra_field="x"))


# ─────────────────────── transformations ─────────────────────────


def test_source_is_not_mutated_by_transformations():
    mr = MRSpec.model_validate(spec())
    followup_of(mr)
    assert mr.source.query_params == {"q": "jazz", "limit": 20}


def test_scale_param_rounds_ints():
    mr = MRSpec.model_validate(
        spec(followups=[{"transformations": [{"op": "scale_param", "param": "limit", "factor": 0.33}]}])
    )
    assert followup_of(mr).query_params["limit"] == 7


@pytest.mark.parametrize(
    "transformation, error",
    [
        ({"op": "scale_param", "param": "q", "factor": 2}, "not numeric"),
        ({"op": "scale_param", "param": "limit", "factor": 1}, "no-op"),
        ({"op": "scale_param", "param": "limit", "factor": 0}, "greater than 0"),
        ({"op": "remove_param", "param": "missing"}, "not present"),
        ({"op": "add_param", "param": "q", "value": "x"}, "already present"),
        ({"op": "append_to_param", "param": "limit", "value": "x"}, "neither string nor list"),
        ({"op": "set_param", "param": "id", "location": "path", "value": [1, 2]}, "scalar"),
        ({"op": "teleport", "param": "q"}, "teleport"),
    ],
)
def test_invalid_transformations(transformation: dict, error: str):
    with pytest.raises(ValidationError, match=error):
        MRSpec.model_validate(spec(followups=[{"transformations": [transformation]}]))


def test_append_to_param_string_and_list():
    mr = MRSpec.model_validate(
        spec(
            source={"path": "/search", "query_params": {"q": "jazz", "tags": ["a"]}},
            followups=[
                {
                    "transformations": [
                        {"op": "append_to_param", "param": "q", "value": "piano"},
                        {"op": "append_to_param", "param": "tags", "value": "b"},
                    ]
                }
            ],
        )
    )
    assert followup_of(mr).query_params == {"q": "jazz piano", "tags": ["a", "b"]}


def test_remove_and_add_param():
    mr = MRSpec.model_validate(
        spec(
            followups=[
                {
                    "transformations": [
                        {"op": "remove_param", "param": "limit"},
                        {"op": "add_param", "param": "category", "value": "vinyl"},
                    ]
                }
            ]
        )
    )
    assert followup_of(mr).query_params == {"q": "jazz", "category": "vinyl"}


def test_move_param_query_to_path_with_new_endpoint():
    mr = MRSpec.model_validate(
        spec(
            source={"path": "/search", "query_params": {"category": "vinyl", "limit": 50}},
            followups=[
                {
                    "path": "/categories/{category}/items",
                    "transformations": [
                        {"op": "move_param", "param": "category", "from_location": "query", "to_location": "path"}
                    ],
                }
            ],
            relation={"type": "equivalence", "source_selector": "$.results[*].id"},
        )
    )
    fu = followup_of(mr)
    assert fu.path == "/categories/{category}/items"
    assert fu.path_params == {"category": "vinyl"}
    assert fu.query_params == {"limit": 50}


def test_followup_path_needs_resolvable_placeholders():
    with pytest.raises(ValidationError, match="missing values"):
        MRSpec.model_validate(
            spec(
                followups=[{"path": "/categories/{category}/items"}],
                relation={"type": "equivalence"},
            )
        )


def test_unused_source_path_params_are_dropped_in_followup():
    mr = MRSpec.model_validate(
        spec(
            source={"path": "/artists/{artist_id}/albums", "path_params": {"artist_id": 7}},
            followups=[
                {
                    "path": "/albums",
                    "transformations": [
                        {
                            "op": "move_param",
                            "param": "artist_id",
                            "from_location": "path",
                            "to_location": "query",
                            "to_param": "artist",
                        }
                    ],
                }
            ],
            relation={"type": "equivalence", "source_selector": "$[*].id"},
        )
    )
    fu = followup_of(mr)
    assert fu.path_params == {}
    assert fu.query_params == {"artist": 7}


# ────────────────────────── relations ────────────────────────────


@pytest.mark.parametrize("rel_type", ["subset", "count_leq"])
def test_directional_relations_require_direction(rel_type: str):
    with pytest.raises(ValidationError, match="requires 'direction'"):
        MRSpec.model_validate(spec(relation={"type": rel_type}))


def test_non_directional_relations_reject_direction():
    with pytest.raises(ValidationError, match="does not accept"):
        MRSpec.model_validate(spec(relation={"type": "equality", "direction": "followup_in_source"}))


def test_measure_only_for_count_leq():
    with pytest.raises(ValidationError, match="only valid for count_leq"):
        MRSpec.model_validate(spec(relation={"type": "equivalence", "measure": "value"}))


def test_selectors_must_be_jsonpath():
    with pytest.raises(ValidationError):
        MRSpec.model_validate(spec(relation={"type": "equality", "source_selector": "results.id"}))


def test_followup_selector_defaults_to_source_selector():
    mr = MRSpec.model_validate(spec())
    assert mr.relation.effective_followup_selector == "$.results[*].id"


def test_complete_and_difference_arity():
    with pytest.raises(ValidationError, match="at least 2"):
        MRSpec.model_validate(spec(relation={"type": "complete"}))
    two = [{"transformations": [{"op": "set_param", "param": "limit", "value": v}]} for v in (5, 10)]
    MRSpec.model_validate(spec(followups=two, relation={"type": "difference"}))
    with pytest.raises(ValidationError, match="exactly 2"):
        MRSpec.model_validate(spec(followups=two[:1], relation={"type": "difference"}))


# ─────────────────────── generation parsing ──────────────────────


def test_parse_generated_relations_keeps_valid_and_reports_invalid():
    bad = spec(source={"method": "POST", "path": "/search"})
    valid, rejected = parse_generated_relations({"relations": [spec(), bad, "garbage"]})
    assert len(valid) == 1
    assert len(rejected) == 2
    assert rejected[0][0] is bad
    assert "source.method" in rejected[0][1]


def test_parse_generated_relations_tolerates_bad_shapes():
    assert parse_generated_relations({}) == ([], [])
    assert parse_generated_relations("nope") == ([], [])  # type: ignore[arg-type]


# ─────────────────────── pipeline state ──────────────────────────


def test_filter_outcome_infers_stage_and_checks_consistency():
    out = FilterOutcome(passed=False, reason=DiscardReason.LOW_FAULT_REVEALING)
    assert out.stage is FilterStage.FAULT_REVEALING
    with pytest.raises(ValidationError):
        FilterOutcome(passed=False)
    with pytest.raises(ValidationError):
        FilterOutcome(passed=True, reason=DiscardReason.REDUNDANT)
    with pytest.raises(ValidationError):
        FilterOutcome(passed=False, reason=DiscardReason.REDUNDANT)  # missing duplicate_of
    with pytest.raises(ValidationError):
        FilterOutcome(passed=False, stage=FilterStage.SEMANTIC, reason=DiscardReason.REDUNDANT, duplicate_of="x")


def _candidate(**overrides) -> dict:
    base = {
        "id": "c1",
        "project_id": "p1",
        "run_id": "r1",
        "spec": spec(),
        "provenance": {"provider": "anthropic", "model": "m", "prompt_version": "gen_v1"},
    }
    base.update(overrides)
    return base


def test_candidate_status_consistency():
    assert MRCandidate.model_validate(_candidate()).status is CandidateStatus.PENDING_REVIEW
    discarded = {"passed": False, "reason": "invalid_semantics"}
    with pytest.raises(ValidationError, match="must have status 'discarded'"):
        MRCandidate.model_validate(_candidate(filter_result=discarded))
    MRCandidate.model_validate(_candidate(filter_result=discarded, status="discarded"))
    with pytest.raises(ValidationError, match="requires a failed filter_result"):
        MRCandidate.model_validate(_candidate(status="discarded"))
    with pytest.raises(ValidationError, match="without spec"):
        MRCandidate.model_validate(_candidate(spec=None))


def test_execution_verdict_aggregation():
    agg = ExecutionResult.aggregate
    assert agg([Verdict.PASS, Verdict.VIOLATION, Verdict.ERROR]) is Verdict.VIOLATION
    assert agg([Verdict.PASS, Verdict.ERROR]) is Verdict.ERROR
    assert agg([Verdict.PASS, Verdict.PASS]) is Verdict.PASS
    assert agg([]) is Verdict.SKIPPED


def test_json_schemas_are_serializable_and_discriminated():
    schemas = json_schemas()
    assert set(schemas) == {"mr_spec", "mr_generation_output", "mr_candidate"}
    dumped = json.dumps(schemas)
    assert '"discriminator"' in dumped
    assert '"GET"' in dumped and '"POST"' not in dumped
