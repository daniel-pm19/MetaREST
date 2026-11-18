"""Mongo documents for platform state, independent of Daniel's executable MR contract."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from app.models.mr import MRCandidate, Provenance
from app.pipeline.llm.config import LLMSettings
from app.pipeline.orchestrator import PipelineSettings, RunReport


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex


class Role(StrEnum):
    ADMIN = "admin"
    QA = "qa"
    OBSERVER = "observer"


class Record(Document):
    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=now)


class UserRecord(Record):
    name: str
    email: str
    password_hash: str
    role: Role
    active: bool = True

    class Settings:
        name = "users"
        indexes = [IndexModel("email", unique=True)]


class ProjectRecord(Record):
    name: str
    base_url: str
    openapi: str
    endpoints: int
    auth_env_key: str | None = None
    max_concurrency: int = 4
    min_interval: float = 0
    timeout: float = 10

    class Settings:
        name = "projects"


class ApiContextRecord(Record):
    project_id: str
    run_id: str
    context: dict[str, Any]

    class Settings:
        name = "api_contexts"


class PromptRecord(Record):
    kind: str
    system: str
    user: str

    class Settings:
        name = "prompt_templates"


def default_platform_settings() -> PipelineSettings:
    """Platform default, independent of the pipeline's historical experiment defaults."""
    return PipelineSettings(llm=LLMSettings(provider="gemini"))


class SettingsRecord(Record):
    id: str = "pipeline"
    pipeline: PipelineSettings = Field(default_factory=default_platform_settings)

    class Settings:
        name = "settings"


class RunRecord(Record):
    project_id: str
    project_name: str
    round: int
    status: str = "running"
    report: RunReport = Field(default_factory=RunReport)
    settings: PipelineSettings
    counts: dict[str, int] = Field(default_factory=dict)
    project_snapshot: dict[str, Any] = Field(default_factory=dict)
    prompts_snapshot: dict[str, dict[str, str]] = Field(default_factory=dict)

    class Settings:
        name = "runs"
        indexes = [
            IndexModel([("project_id", 1), ("round", 1)], unique=True),
            IndexModel("project_id", unique=True, partialFilterExpression={"status": "running"}),
        ]


class CandidateRecord(Record):
    candidate: MRCandidate

    class Settings:
        name = "candidates"
        indexes = ["candidate.run_id", "candidate.project_id"]


class DecisionRecord(Record):
    candidate_id: str
    run_id: str
    user_id: str
    user: str
    title: str
    decision: str
    justification: str | None = None
    review_time_ms: int | None = None
    provenance: Provenance

    class Settings:
        name = "decisions"
        indexes = [IndexModel("candidate_id", unique=True), "run_id"]


class AuditRecord(Record):
    user_id: str
    action: str
    resource_id: str

    class Settings:
        name = "audit_log"


DOCUMENTS = [
    UserRecord,
    ProjectRecord,
    ApiContextRecord,
    PromptRecord,
    SettingsRecord,
    RunRecord,
    CandidateRecord,
    DecisionRecord,
    AuditRecord,
]
