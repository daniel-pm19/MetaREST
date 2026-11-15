"""Validated HTTP contracts consumed by the existing frontend."""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.platform import Role
from app.pipeline.orchestrator import RunReport


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class NewUser(Input):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    role: Role
    password: str

    @field_validator("password")
    @classmethod
    def password_size(cls, value):
        if not 12 <= len(value.encode("utf-8")) <= 72:
            raise ValueError("La contraseña debe tener entre 12 y 72 bytes UTF-8")
        return value


class UserPatch(Input):
    role: Role | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def non_null(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("role y active no admiten null")
        return self


class NewProject(Input):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(max_length=2000)
    openapi: str = Field(min_length=1, max_length=2_000_000)
    auth_env_key: str | None = Field(default=None, pattern=r"^SUT_[A-Z0-9_]+$")
    max_concurrency: int = Field(default=4, ge=1, le=16)
    min_interval: float = Field(default=0, ge=0, le=60)
    timeout: float = Field(default=10, gt=0, le=120)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("URL HTTP(S) sin credenciales, query ni fragmento requerida")
        return value.rstrip("/")


class DecisionInput(Input):
    decision: Literal["accepted", "rejected"]
    justification: str | None = Field(default=None, max_length=4000)
    review_time_ms: int | None = Field(default=None, ge=0, le=86_400_000)

    @model_validator(mode="after")
    def rejection_reason(self):
        if self.justification is not None:
            self.justification = self.justification.strip()
        if self.decision == "rejected" and not self.justification:
            raise ValueError("Rechazar exige una justificación")
        return self


class NewPrompt(Input):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    kind: Literal["generation", "semantic", "fault"]
    system: str = Field(min_length=1, max_length=50000)
    user: str = Field(min_length=1, max_length=50000)


class UserOutput(BaseModel):
    id: str
    name: str
    email: str
    role: Role
    active: bool


class LoginOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOutput


class ProjectOutput(BaseModel):
    id: str
    name: str
    base_url: str
    endpoints: int
    created_at: datetime


class RunOutput(BaseModel):
    id: str
    project_id: str
    project_name: str
    round: int
    status: Literal["running", "awaiting_review", "failed"]
    report: RunReport
    counts: dict[str, int]


class PromptOutput(NewPrompt):
    editable: bool


class MetricsOutput(BaseModel):
    run_id: str
    round: int
    generated: int
    discarded: int
    pending: int
    accepted: int
    rejected: int
    violations: int
    confirmed_faults: int
    acceptance_rate: float | None
    tokens: int
    avg_combined: int
    avg_review_ms: int | None
