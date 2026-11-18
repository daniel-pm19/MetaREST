"""Regression tests for platform defaults, migrations and per-project auth."""

import json

import pytest

from app.models.platform import RunRecord, SettingsRecord, default_platform_settings
from app.pipeline.llm.config import DEFAULT_MODELS, LLMSettings
from scripts.configure_gemini import configure_gemini
from tests.test_platform_api import authorization, create_project, platform  # noqa: F401


def test_platform_defaults_to_gemini_without_changing_experiment_defaults():
    settings = default_platform_settings()
    assert settings.llm.provider == "gemini"
    assert (settings.llm.generation_model, settings.llm.verification_model) == DEFAULT_MODELS["gemini"]
    assert settings.llm.verification_effort == "medium"
    assert settings.llm.requests_per_minute == 12
    assert LLMSettings().provider == "anthropic"  # Historical pipeline/experiment contract remains unchanged.


async def test_new_database_exposes_gemini_defaults(platform):  # noqa: F811
    response = await platform[0].get("/settings/llm", headers=authorization(platform))
    assert response.status_code == 200
    assert response.json()["provider"] == "gemini"


async def test_existing_settings_are_not_silently_changed_on_startup(platform):  # noqa: F811
    from app.db import initialize_database

    _, app, _ = platform
    settings = await SettingsRecord.get("pipeline")
    settings.pipeline.llm = LLMSettings(provider="anthropic", max_candidates=7)
    await settings.replace()
    await initialize_database(app.state.settings, app.state.mongo)
    assert (await SettingsRecord.get("pipeline")).pipeline.llm.provider == "anthropic"


async def test_explicit_migration_preserves_general_settings_and_run_history(platform):  # noqa: F811
    record = await SettingsRecord.get("pipeline")
    record.pipeline.llm = LLMSettings(provider="anthropic", max_candidates=7, timeout_seconds=123, max_retries=1)
    record.pipeline.filters.min_semantic = 0.71
    await record.replace()
    historical = RunRecord(
        project_id="old-project",
        project_name="Historical",
        round=1,
        status="awaiting_review",
        settings=record.pipeline.model_copy(deep=True),
    )
    await historical.insert()
    before = (await RunRecord.get(historical.id)).model_dump(mode="json")
    preview = await configure_gemini()
    assert preview["changed"] and not preview["applied"]
    assert (await SettingsRecord.get("pipeline")).pipeline.llm.provider == "anthropic"
    assert (await configure_gemini(apply=True))["applied"]
    updated = (await SettingsRecord.get("pipeline")).pipeline
    assert updated.llm.provider == "gemini"
    assert updated.llm.max_candidates == 7 and updated.llm.timeout_seconds == 123 and updated.llm.max_retries == 1
    assert updated.filters.min_semantic == 0.71
    assert updated.llm.requests_per_minute == 12
    assert (await RunRecord.get(historical.id)).model_dump(mode="json") == before
    assert not (await configure_gemini(apply=True))["changed"]


async def test_migration_keeps_already_configured_gemini_models(platform):  # noqa: F811
    record = await SettingsRecord.get("pipeline")
    record.pipeline.llm = LLMSettings(provider="gemini", generation_model="custom-model", requests_per_minute=5)
    await record.replace()
    before = record.pipeline.model_dump()
    assert not (await configure_gemini(apply=True))["changed"]
    assert (await SettingsRecord.get("pipeline")).pipeline.model_dump() == before


async def test_migration_repairs_gemini_with_stale_claude_models(platform):  # noqa: F811
    record = await SettingsRecord.get("pipeline")
    record.pipeline.llm = LLMSettings(
        provider="gemini",
        generation_model="claude-sonnet-5-5",
        verification_model="claude-haiku-5-5",
        max_candidates=3,
    )
    await record.replace()
    assert (await configure_gemini(apply=True))["applied"]
    updated = (await SettingsRecord.get("pipeline")).pipeline.llm
    assert (updated.generation_model, updated.verification_model) == DEFAULT_MODELS["gemini"]
    assert updated.max_candidates == 3


@pytest.mark.parametrize("path", ["/settings/llm", "/settings/pipeline"])
async def test_settings_refuse_mixed_provider_and_models(platform, path):  # noqa: F811
    invalid = {"provider": "gemini", "generation_model": "claude-sonnet-5-5"}
    body = {"llm": invalid} if path.endswith("pipeline") else invalid
    response = await platform[0].put(path, headers=authorization(platform), json=body)
    assert response.status_code == 422
    assert (await SettingsRecord.get("pipeline")).pipeline.llm.generation_model == DEFAULT_MODELS["gemini"][0]


async def test_authenticated_and_public_runs_do_not_share_headers(platform, monkeypatch):  # noqa: F811
    from app import services
    from app.pipeline.embeddings import HashingEmbedder
    from app.pipeline.executor import SUTClient
    from tests.conftest import fake_sut
    from tests.test_orchestrator import scripted_llm

    received = []
    transport = fake_sut.__wrapped__()(calls=received)
    monkeypatch.setenv("SUT_PRIVATE_HEADERS", json.dumps({"Authorization": "Bearer project-secret"}))
    monkeypatch.setenv("SUT_HEADERS_JSON", json.dumps({"Authorization": "Bearer old-global-secret"}))
    monkeypatch.setattr(services, "create_provider", lambda _: scripted_llm())
    monkeypatch.setattr(services, "FastEmbedEmbedder", lambda *a, **kw: HashingEmbedder())
    monkeypatch.setattr(services, "SUTClient", lambda base, **kw: SUTClient(base, transport=transport, **kw))
    public = await create_project(platform)
    from app.models.platform import ProjectRecord

    record = await ProjectRecord.get(public["id"])
    private = await ProjectRecord(
        **{
            **record.model_dump(exclude={"id", "revision_id"}),
            "name": "Private",
            "auth_env_key": "SUT_PRIVATE_HEADERS",
        }
    ).insert()
    client = platform[0]
    headers = authorization(platform)
    for project_id, expected in ((private.id, "Bearer project-secret"), (public["id"], None)):
        received.clear()
        response = await client.post(f"/projects/{project_id}/runs", headers=headers)
        assert response.status_code == 202
        result = await RunRecord.get(response.json()["id"])
        assert result.status == "awaiting_review", result.report.error
        assert received
        assert all(request.headers.get("authorization") == expected for request in received)


async def test_missing_project_credentials_fail_before_provider_or_sut(platform, monkeypatch):  # noqa: F811
    from app import services
    from app.models.platform import ProjectRecord

    project = await create_project(platform)
    await ProjectRecord.find_one(ProjectRecord.id == project["id"]).update(
        {"$set": {"auth_env_key": "SUT_MISSING_HEADERS"}}
    )
    monkeypatch.delenv("SUT_MISSING_HEADERS", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("No LLM or SUT call should occur with missing credentials")

    monkeypatch.setattr(services, "create_provider", forbidden)
    monkeypatch.setattr(services, "SUTClient", forbidden)
    response = await platform[0].post(f"/projects/{project['id']}/runs", headers=authorization(platform))
    result = await RunRecord.get(response.json()["id"])
    assert result.status == "failed"
    assert "SUT_MISSING_HEADERS" in result.report.error
