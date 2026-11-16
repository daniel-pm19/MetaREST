"""Executable Metamorphic Relation (MR) contract.

This module is the single source of truth for what an MR is in MetaREST:

* ``MRSpec``       -- what the LLM generates. Fully structured and executable:
                      a source request, one or more follow-up requests derived
                      from it through a closed catalog of transformations, and
                      a relation from a closed catalog that must hold between
                      the selected parts of their responses.
* ``MRCandidate``  -- an ``MRSpec`` plus the pipeline state attached to it
                      (provenance, filter scores, execution evidence, review status).

Human-readable semantics, examples and rules live in ``docs/MR_SCHEMA.md``.
Changing this file changes the contract shared by the pipeline, the API and the
frontend: agree on it with Daniel before pushing (see AGENTS.md).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SCHEMA_VERSION = "1.0"

MAX_FOLLOWUPS = 4
MAX_TRANSFORMATIONS = 5
MAX_INPUT_VARIANTS = 2

Scalar = str | int | float | bool
ParamValue = Scalar | list[Scalar]

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.\-]*)\}")


class MRNotExecutableError(ValueError):
    """Raised when an MR cannot be turned into concrete HTTP requests."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# ─────────────────────────────── Requests ────────────────────────────────


class HttpMethod(StrEnum):
    """Only safe methods: the executor never mutates the system under test."""

    GET = "GET"
    HEAD = "HEAD"


class ParamLocation(StrEnum):
    QUERY = "query"
    PATH = "path"


def path_placeholders(path: str) -> set[str]:
    return set(_PLACEHOLDER.findall(path))


class RequestSpec(_Model):
    """A concrete request against the API under test (base URL excluded)."""

    method: HttpMethod = HttpMethod.GET
    path: str = Field(
        pattern=r"^/",
        max_length=500,
        description="OpenAPI path template, e.g. /items/{id}. Must exist in the spec.",
    )
    path_params: dict[str, Scalar] = Field(
        default_factory=dict,
        description="Value for every {placeholder} in path, and nothing else.",
    )
    query_params: dict[str, ParamValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _path_params_match_placeholders(self) -> RequestSpec:
        placeholders = path_placeholders(self.path)
        missing = placeholders - self.path_params.keys()
        extra = self.path_params.keys() - placeholders
        if missing:
            raise MRNotExecutableError(f"path {self.path!r} is missing values for {sorted(missing)}")
        if extra:
            raise MRNotExecutableError(f"path_params {sorted(extra)} are not placeholders of {self.path!r}")
        return self


class InputVariant(_Model):
    """Extra input instance: overrides merged on top of the source request params."""

    path_params: dict[str, Scalar] = Field(default_factory=dict)
    query_params: dict[str, ParamValue] = Field(default_factory=dict)


# ──────────────────────────── Transformations ────────────────────────────


class SetParam(_Model):
    """Set (or overwrite) a parameter of the follow-up request."""

    op: Literal["set_param"]
    param: str
    location: ParamLocation = ParamLocation.QUERY
    value: ParamValue


class RemoveParam(_Model):
    """Remove a query parameter present in the source request."""

    op: Literal["remove_param"]
    param: str


class AddParam(_Model):
    """Add a query parameter absent from the source request."""

    op: Literal["add_param"]
    param: str
    value: ParamValue


class ScaleParam(_Model):
    """Multiply a numeric parameter by ``factor`` (e.g. halve a page size)."""

    op: Literal["scale_param"]
    param: str
    location: ParamLocation = ParamLocation.QUERY
    factor: float = Field(gt=0)
    round_to_int: bool = Field(default=True, description="If the original value is an int, round the result to int.")

    @model_validator(mode="after")
    def _factor_not_identity(self) -> ScaleParam:
        if self.factor == 1:
            raise MRNotExecutableError("scale_param with factor 1 is a no-op")
        return self


class AppendToParam(_Model):
    """Append to a string query param (joined by ``separator``) or to a list param."""

    op: Literal["append_to_param"]
    param: str
    value: Scalar
    separator: str = " "


class MoveParam(_Model):
    """Move a value between parameters/locations (e.g. ?category=x -> /categories/{category})."""

    op: Literal["move_param"]
    param: str
    from_location: ParamLocation
    to_location: ParamLocation
    to_param: str | None = Field(default=None, description="Target name; defaults to `param`.")


Transformation = Annotated[
    SetParam | RemoveParam | AddParam | ScaleParam | AppendToParam | MoveParam,
    Field(discriminator="op"),
]


class FollowupSpec(_Model):
    """A follow-up request derived from the source request."""

    method: HttpMethod = HttpMethod.GET
    path: str | None = Field(
        default=None,
        pattern=r"^/",
        max_length=500,
        description="Target endpoint. Omit to reuse the source path.",
    )
    transformations: list[Transformation] = Field(default_factory=list, max_length=MAX_TRANSFORMATIONS)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _apply(t: Transformation, query: dict[str, ParamValue], path: dict[str, ParamValue]) -> None:
    def target(location: ParamLocation) -> dict[str, ParamValue]:
        return query if location is ParamLocation.QUERY else path

    def require(params: dict[str, ParamValue], name: str, location: str) -> ParamValue:
        if name not in params:
            raise MRNotExecutableError(f"{t.op}: {location} param {name!r} not present in source request")
        return params[name]

    match t:
        case SetParam():
            if t.location is ParamLocation.PATH and isinstance(t.value, list):
                raise MRNotExecutableError("set_param: path params must be scalar")
            target(t.location)[t.param] = t.value
        case RemoveParam():
            require(query, t.param, "query")
            del query[t.param]
        case AddParam():
            if t.param in query:
                raise MRNotExecutableError(f"add_param: {t.param!r} already present; use set_param")
            query[t.param] = t.value
        case ScaleParam():
            params = target(t.location)
            current = require(params, t.param, t.location.value)
            if not _is_number(current):
                raise MRNotExecutableError(f"scale_param: {t.param!r} is not numeric ({current!r})")
            scaled = current * t.factor
            params[t.param] = int(round(scaled)) if isinstance(current, int) and t.round_to_int else scaled
        case AppendToParam():
            current = require(query, t.param, "query")
            if isinstance(current, list):
                query[t.param] = [*current, t.value]
            elif isinstance(current, str):
                query[t.param] = f"{current}{t.separator}{t.value}"
            else:
                raise MRNotExecutableError(f"append_to_param: {t.param!r} is neither string nor list")
        case MoveParam():
            value = require(target(t.from_location), t.param, t.from_location.value)
            del target(t.from_location)[t.param]
            if t.to_location is ParamLocation.PATH and isinstance(value, list):
                raise MRNotExecutableError("move_param: path params must be scalar")
            target(t.to_location)[t.to_param or t.param] = value


def derive_followup(source: RequestSpec, followup: FollowupSpec) -> RequestSpec:
    """Build the concrete follow-up request.

    The follow-up starts as a copy of the source params, applies the
    transformations in order, then keeps only the path params that the
    follow-up path actually uses.
    """
    query: dict[str, ParamValue] = copy.deepcopy(source.query_params)
    path_params: dict[str, ParamValue] = dict(source.path_params)
    for t in followup.transformations:
        _apply(t, query, path_params)
    target_path = followup.path or source.path
    used = path_placeholders(target_path)
    return RequestSpec(
        method=followup.method,
        path=target_path,
        path_params={k: v for k, v in path_params.items() if k in used},  # type: ignore[misc]
        query_params=query,
    )


# ─────────────────────────────── Relations ───────────────────────────────


class RelationType(StrEnum):
    """Closed catalog. Semantics (S = source selection, Fi = follow-up i selection)
    are documented in docs/MR_SCHEMA.md and implemented by the executor."""

    EQUALITY = "equality"  # Fi == S (same elements, same order)
    EQUIVALENCE = "equivalence"  # Fi == S as multisets (order ignored)
    SUBSET = "subset"  # set(Fi) ⊆ set(S) or set(S) ⊆ set(Fi), per direction
    DISJOINT = "disjoint"  # S, F1..Fn pairwise disjoint
    COMPLETE = "complete"  # set(S) == ⋃ set(Fi)            (>= 2 follow-ups)
    DIFFERENCE = "difference"  # set(S) \ set(F1) == set(F2)  (exactly 2 follow-ups)
    COUNT_LEQ = "count_leq"  # measure(Fi) <= measure(S) or reverse, per direction
    SAME_ORDER = "same_order"  # elements common to S and Fi keep their relative order


class Direction(StrEnum):
    FOLLOWUP_IN_SOURCE = "followup_in_source"  # subset: Fi ⊆ S   | count_leq: Fi <= S
    SOURCE_IN_FOLLOWUP = "source_in_followup"  # subset: S ⊆ Fi   | count_leq: S <= Fi


class Measure(StrEnum):
    COUNT = "count"  # number of selected elements
    VALUE = "value"  # the selector must yield exactly one number (e.g. $.total)


_DIRECTIONAL = {RelationType.SUBSET, RelationType.COUNT_LEQ}


class RelationSpec(_Model):
    type: RelationType
    source_selector: str = Field(
        default="$",
        pattern=r"^\$",
        max_length=300,
        description="JSONPath applied to the source response body, e.g. $.results[*].id",
    )
    followup_selector: str | None = Field(
        default=None,
        pattern=r"^\$",
        max_length=300,
        description="JSONPath applied to each follow-up response. Defaults to source_selector.",
    )
    direction: Direction | None = Field(default=None, description="Required for subset and count_leq only.")
    measure: Measure = Field(default=Measure.COUNT, description="Only meaningful for count_leq.")

    @model_validator(mode="after")
    def _check_options(self) -> RelationSpec:
        if self.type in _DIRECTIONAL and self.direction is None:
            raise MRNotExecutableError(f"relation {self.type.value!r} requires 'direction'")
        if self.type not in _DIRECTIONAL and self.direction is not None:
            raise MRNotExecutableError(f"relation {self.type.value!r} does not accept 'direction'")
        if self.type is not RelationType.COUNT_LEQ and self.measure is not Measure.COUNT:
            raise MRNotExecutableError("'measure' is only valid for count_leq")
        return self

    @property
    def effective_followup_selector(self) -> str:
        return self.followup_selector or self.source_selector


# ──────────────────────────────── MR spec ────────────────────────────────


class MRSpec(_Model):
    """An executable metamorphic relation, as produced by the LLM."""

    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3, max_length=1000)
    source: RequestSpec
    followups: list[FollowupSpec] = Field(min_length=1, max_length=MAX_FOLLOWUPS)
    relation: RelationSpec
    transformation_logic: str = Field(min_length=3, max_length=500, description="How the input is changed.")
    expected_relation: str = Field(min_length=3, max_length=500, description="What must hold between outputs.")
    rationale: str = Field(min_length=3, max_length=1000, description="Which fault this MR could reveal and why.")
    input_variants: list[InputVariant] = Field(default_factory=list, max_length=MAX_INPUT_VARIANTS)

    @model_validator(mode="after")
    def _check_executable(self) -> MRSpec:
        n = len(self.followups)
        if self.relation.type is RelationType.COMPLETE and n < 2:
            raise MRNotExecutableError("relation 'complete' requires at least 2 follow-ups")
        if self.relation.type is RelationType.DIFFERENCE and n != 2:
            raise MRNotExecutableError("relation 'difference' requires exactly 2 follow-ups")
        self.instances()  # every instance must derive into valid concrete requests
        return self

    def source_instances(self) -> list[RequestSpec]:
        """The base source request plus one request per input variant."""
        base = self.source
        variants = [
            RequestSpec(
                method=base.method,
                path=base.path,
                path_params={**base.path_params, **v.path_params},
                query_params={**base.query_params, **v.query_params},
            )
            for v in self.input_variants
        ]
        return [base, *variants]

    def instances(self) -> list[tuple[RequestSpec, list[RequestSpec]]]:
        """Concrete (source, [follow-ups]) pairs the executor will run."""
        return [(src, [derive_followup(src, f) for f in self.followups]) for src in self.source_instances()]


class MRGenerationOutput(_Model):
    """Tool-use input schema the LLM must fill during generation."""

    relations: list[MRSpec] = Field(min_length=1, max_length=50)


def parse_generated_relations(raw: dict[str, Any]) -> tuple[list[MRSpec], list[tuple[Any, str]]]:
    """Validate each generated MR on its own.

    Returns ``(valid, rejected)`` where ``rejected`` holds ``(raw_item, error)``.
    A single malformed MR must not discard the whole batch: rejected items are
    stored as ``not_executable`` candidates (they count for RQ1).
    """
    items: Iterable[Any] = raw.get("relations", []) if isinstance(raw, dict) else []
    valid: list[MRSpec] = []
    rejected: list[tuple[Any, str]] = []
    for item in items:
        try:
            valid.append(MRSpec.model_validate(item))
        except ValidationError as exc:
            rejected.append((item, _short_error(exc)))
    return valid, rejected


def _short_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors(include_url=False):
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)[:1000]


# ─────────────────────────── Pipeline state ──────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


class Provenance(_Model):
    provider: str = Field(description="e.g. anthropic")
    model: str = Field(description="e.g. claude-sonnet-5-5")
    prompt_version: str = Field(description="e.g. gen_v1")
    generated_at: datetime = Field(default_factory=_now)


class CriterionScore(_Model):
    """Result of one filter criterion (rules + optional LLM check)."""

    rules_passed: bool
    rule_violations: list[str] = Field(default_factory=list)
    llm_score: float | None = Field(default=None, ge=0, le=1)
    llm_reason: str | None = Field(default=None, max_length=1000)
    score: float = Field(ge=0, le=1, description="Final score of this criterion.")


class Scores(_Model):
    semantic_validity: CriterionScore | None = None
    fault_revealing: CriterionScore | None = None
    max_similarity: float | None = Field(
        default=None, ge=-1, le=1, description="Highest cosine similarity to an already selected MR."
    )
    combined: float | None = Field(default=None, ge=0, le=1)


class FilterStage(StrEnum):
    SCHEMA = "schema"
    SEMANTIC = "semantic"
    FAULT_REVEALING = "fault_revealing"
    DIVERSITY = "diversity"


class DiscardReason(StrEnum):
    NOT_EXECUTABLE = "not_executable"  # failed MRSpec validation
    INVALID_SEMANTICS = "invalid_semantics"  # not supported by the OpenAPI spec
    LOW_FAULT_REVEALING = "low_fault_revealing"  # trivial / tautological / below threshold
    REDUNDANT = "redundant"  # too similar to a higher-scored MR (see duplicate_of)


_STAGE_FOR_REASON = {
    DiscardReason.NOT_EXECUTABLE: FilterStage.SCHEMA,
    DiscardReason.INVALID_SEMANTICS: FilterStage.SEMANTIC,
    DiscardReason.LOW_FAULT_REVEALING: FilterStage.FAULT_REVEALING,
    DiscardReason.REDUNDANT: FilterStage.DIVERSITY,
}


class FilterOutcome(_Model):
    passed: bool
    stage: FilterStage | None = Field(default=None, description="Stage that discarded the MR.")
    reason: DiscardReason | None = None
    detail: str | None = Field(default=None, max_length=1000)
    duplicate_of: str | None = Field(default=None, description="Candidate id this MR is redundant with.")

    @model_validator(mode="after")
    def _consistent(self) -> FilterOutcome:
        if self.passed:
            if self.stage or self.reason or self.duplicate_of:
                raise ValueError("a passed MR has no stage, reason or duplicate_of")
            return self
        if self.reason is None:
            raise ValueError("a discarded MR needs a reason")
        if self.stage is None:
            self.stage = _STAGE_FOR_REASON[self.reason]
        elif self.stage is not _STAGE_FOR_REASON[self.reason]:
            raise ValueError(f"reason {self.reason.value!r} does not belong to stage {self.stage.value!r}")
        if (self.reason is DiscardReason.REDUNDANT) != (self.duplicate_of is not None):
            raise ValueError("duplicate_of is required for, and only for, redundant MRs")
        return self


class Verdict(StrEnum):
    PASS = "pass"  # relation held in every instance
    VIOLATION = "violation"  # relation broken in at least one instance -> possible fault
    ERROR = "error"  # request failed / non-2xx / selector found nothing
    SKIPPED = "skipped"  # not executed (e.g. discarded before execution)


class HttpExchange(_Model):
    method: HttpMethod
    url: str
    status_code: int | None = None
    elapsed_ms: float | None = None
    response_excerpt: str | None = Field(default=None, max_length=4000)
    selected_excerpt: str | None = Field(default=None, max_length=2000, description="Selector output.")
    from_cache: bool = False
    error: str | None = Field(default=None, max_length=1000)


class InstanceExecution(_Model):
    index: int = Field(ge=0, description="0 = base source, 1.. = input variants")
    source: HttpExchange
    followups: list[HttpExchange]
    verdict: Verdict
    message: str | None = Field(default=None, max_length=1000)


class ExecutionResult(_Model):
    verdict: Verdict
    instances: list[InstanceExecution] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=_now)

    @staticmethod
    def aggregate(verdicts: Iterable[Verdict]) -> Verdict:
        """violation > error > pass. Empty -> skipped."""
        vs = set(verdicts)
        for v in (Verdict.VIOLATION, Verdict.ERROR, Verdict.PASS):
            if v in vs:
                return v
        return Verdict.SKIPPED


class CandidateStatus(StrEnum):
    DISCARDED = "discarded"  # removed by the automatic filter (final)
    PENDING_REVIEW = "pending_review"  # passed the filter, waiting for the QA Auditor
    ACCEPTED = "accepted"
    REJECTED = "rejected"  # requires a written justification (stored in `decisions`)


class MRCandidate(_Model):
    """An MR plus everything the pipeline and the reviewer attached to it."""

    id: str
    project_id: str
    run_id: str
    schema_version: str = SCHEMA_VERSION
    spec: MRSpec | None = Field(default=None, description="None only when the LLM output was not executable.")
    raw_output: Any | None = Field(default=None, description="Original LLM item, kept when spec is None.")
    provenance: Provenance
    scores: Scores = Field(default_factory=Scores)
    filter_result: FilterOutcome | None = None
    execution: ExecutionResult | None = None
    status: CandidateStatus = CandidateStatus.PENDING_REVIEW

    @model_validator(mode="after")
    def _consistent(self) -> MRCandidate:
        if self.spec is None:
            if self.filter_result is None or self.filter_result.reason is not DiscardReason.NOT_EXECUTABLE:
                raise ValueError("a candidate without spec must be discarded as not_executable")
        if self.filter_result is not None and not self.filter_result.passed:
            if self.status is not CandidateStatus.DISCARDED:
                raise ValueError("a candidate discarded by the filter must have status 'discarded'")
        if self.status is CandidateStatus.DISCARDED and (self.filter_result is None or self.filter_result.passed):
            raise ValueError("status 'discarded' requires a failed filter_result")
        return self


def json_schemas() -> dict[str, dict[str, Any]]:
    """JSON Schemas exported to docs/schemas/ (reference + frontend mocks; the LLM gets app.pipeline.wire)."""
    return {
        "mr_spec": MRSpec.model_json_schema(),
        "mr_generation_output": MRGenerationOutput.model_json_schema(),
        "mr_candidate": MRCandidate.model_json_schema(),
    }
