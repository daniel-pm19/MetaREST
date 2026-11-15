"""Platform integration/RBAC against Mongo-compatible storage and a fake LLM.

No API keys or embedding downloads; the real team's orchestrator is exercised.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.auth import hash_password, issue_token
from app.config import Settings
from app.main import create_app
from app.models.platform import CandidateRecord, DecisionRecord, Role, RunRecord, SettingsRecord, UserRecord

PASSWORD = "platform-test-password"
SECRET = "test-only-jwt-secret-with-more-than-32-characters"
SPEC = (Path(__file__).parent / "fixtures/openapi_search.yaml").read_text(encoding="utf-8")


@lru_cache
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
async def platform():
    settings = Settings(_env_file=None, jwt_secret=SECRET, mongodb_database="metarest_test_" + uuid4().hex)
    uri = os.getenv("TEST_MONGODB_URI")
    mongo = AsyncIOMotorClient(uri, tz_aware=True) if uri else AsyncMongoMockClient(tz_aware=True)
    app = create_app(settings, mongo_client=mongo)
    async with app.router.lifespan_context(app):
        users = {}
        for role in Role:
            users[role.value] = await UserRecord(
                name=role.value,
                email=f"{role.value}@example.com",
                role=role,
                password_hash=password_hash(),
            ).insert()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://platform") as client:
            try:
                yield client, app, users
            finally:
                await mongo.drop_database(settings.mongodb_database)
                mongo.close()


def authorization(platform, role="admin"):
    _, app, users = platform
    return {"Authorization": "Bearer " + issue_token(users[role], app.state.settings)}


async def create_project(platform):
    client, _, _ = platform
    response = await client.post(
        "/projects",
        headers=authorization(platform, "qa"),
        json={
            "name": "Demo",
            "base_url": "http://sut.test",
            "openapi": SPEC,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_health_login_me_and_secret_redaction(platform):
    client, _, _ = platform
    assert (await client.get("/health")).json() == {"status": "ok"}
    response = await client.post("/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["role"] == "admin"
    assert "password" not in json.dumps(body)
    assert (
        await client.get("/auth/me", headers={"Authorization": "Bearer " + body["access_token"]})
    ).status_code == 200
    assert (
        await client.post("/auth/login", json={"email": "unknown@example.com", "password": PASSWORD})
    ).status_code == 401
    assert (await client.get("/projects")).status_code == 401


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("GET", "/users", None),
        ("POST", "/users", {}),
        ("PATCH", "/users/no-user", {}),
        ("GET", "/settings/llm", None),
        ("PUT", "/settings/llm", {}),
        ("GET", "/settings/thresholds", None),
        ("PUT", "/settings/thresholds", {}),
        ("GET", "/prompts", None),
        ("POST", "/prompts", {}),
        ("PUT", "/settings/pipeline", {}),
    ],
)
async def test_admin_routes_reject_non_admins(platform, method, path, payload):
    client, _, _ = platform
    for role in ("qa", "observer"):
        response = await client.request(method, path, headers=authorization(platform, role), json=payload)
        assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", "/projects", {}),
        ("PUT", "/projects/missing", {}),
        ("POST", "/projects/missing/runs", None),
        ("POST", "/candidates/missing/decision", {"decision": "accepted"}),
        ("GET", "/candidates/export?run_id=missing", None),
    ],
)
async def test_observer_cannot_write_or_export(platform, method, path, payload):
    response = await platform[0].request(method, path, headers=authorization(platform, "observer"), json=payload)
    assert response.status_code == 403


async def test_user_crud_revokes_existing_tokens_and_protects_self(platform):
    client, app, users = platform
    headers = authorization(platform)
    created = await client.post(
        "/users",
        headers=headers,
        json={
            "name": "New QA",
            "email": "new@example.com",
            "role": "qa",
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    assert "password" not in created.text
    assert (
        await client.post(
            "/users",
            headers=headers,
            json={
                "name": "Duplicate",
                "email": "NEW@example.com",
                "role": "qa",
                "password": PASSWORD,
            },
        )
    ).status_code == 409
    assert (
        await client.patch(f"/users/{users['admin'].id}", headers=headers, json={"active": False})
    ).status_code == 400
    old_token = issue_token(users["qa"], app.state.settings)
    assert (await client.patch(f"/users/{users['qa'].id}", headers=headers, json={"active": False})).status_code == 200
    assert (await client.get("/projects", headers={"Authorization": "Bearer " + old_token})).status_code == 401


async def test_expired_token_and_password_validation_dont_echo_secrets(platform):
    client, _, users = platform
    token = jwt.encode(
        {
            "sub": users["qa"].id,
            "iss": "metarest",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    assert (await client.get("/projects", headers={"Authorization": "Bearer " + token})).status_code == 401
    response = await client.post(
        "/users",
        headers=authorization(platform),
        json={
            "name": "Test",
            "email": "test@example.com",
            "role": "qa",
            "password": "short-secret",
        },
    )
    assert response.status_code == 201  # twelve bytes is the documented minimum
    response = await client.post(
        "/users",
        headers=authorization(platform),
        json={
            "name": "Test",
            "email": "test2@example.com",
            "role": "qa",
            "password": "short",
        },
    )
    assert response.status_code == 422
    assert '"input"' not in response.text


async def test_projects_validate_spec_and_base_url(platform):
    project = await create_project(platform)
    client, _, _ = platform
    assert project["endpoints"] >= 1
    assert len((await client.get("/projects", headers=authorization(platform, "observer"))).json()) == 1
    for base, spec in [("http://user:secret@host", SPEC), ("http://host", "not an OpenAPI")]:
        response = await client.post(
            "/projects",
            headers=authorization(platform),
            json={
                "name": "Invalid",
                "base_url": base,
                "openapi": spec,
            },
        )
        assert response.status_code == 422


async def test_run_end_to_end_uses_real_orchestrator_exports_and_append_only_decisions(platform, monkeypatch):
    from app import services
    from app.pipeline.embeddings import HashingEmbedder
    from app.pipeline.executor import SUTClient
    from tests.conftest import fake_sut
    from tests.test_orchestrator import scripted_llm

    transport = fake_sut.__wrapped__()()
    monkeypatch.setattr(services, "create_provider", lambda _: scripted_llm())
    monkeypatch.setattr(services, "FastEmbedEmbedder", lambda *a, **kw: HashingEmbedder())
    monkeypatch.setattr(services, "SUTClient", lambda base, **kw: SUTClient(base, transport=transport, **kw))
    project = await create_project(platform)
    client, _, _ = platform
    started = await client.post(f"/projects/{project['id']}/runs", headers=authorization(platform, "qa"))
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    polled = (await client.get(f"/runs/{run_id}", headers=authorization(platform, "observer"))).json()
    assert polled["status"] == "awaiting_review", polled
    assert all(stage["status"] == "done" for stage in polled["report"]["stages"])
    values = (await client.get(f"/runs/{run_id}/candidates", headers=authorization(platform))).json()
    pending = next(c for c in values if c["status"] == "pending_review")
    path = f"/candidates/{pending['id']}/decision"
    assert (
        await client.post(path, headers=authorization(platform, "qa"), json={"decision": "rejected"})
    ).status_code == 422
    responses = await asyncio.gather(
        *[
            client.post(
                path, headers=authorization(platform, "qa"), json={"decision": "accepted", "review_time_ms": 1200}
            )
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert await DecisionRecord.find_all().count() == 1
    # Simulate interruption after the authoritative append and before materialized status update.
    await CandidateRecord.find_one(CandidateRecord.id == pending["id"]).update(
        {
            "$set": {"candidate.status": "pending_review"},
        }
    )
    exported = (await client.get(f"/candidates/export?run_id={run_id}", headers=authorization(platform))).json()
    assert set(exported) == {"settings", "report", "candidates"}
    assert len(exported["candidates"]) == len(values)
    assert next(c for c in exported["candidates"] if c["id"] == pending["id"])["status"] == "accepted"
    assert any(c["status"] == "discarded" for c in exported["candidates"])
    audit = (await client.get(f"/audit?run_id={run_id}", headers=authorization(platform, "observer"))).json()
    assert audit[0]["review_time_ms"] == 1200
    assert audit[0]["provenance"]["prompt_version"]
    assert (await client.delete(f"/audit/{audit[0]['id']}", headers=authorization(platform))).status_code == 404
    metric = (await client.get(f"/metrics/compare?runs={run_id}", headers=authorization(platform))).json()[0]
    assert metric["accepted"] == 1 and metric["avg_review_ms"] == 1200
    assert (
        (await client.get(f"/candidates/export?run_id={run_id}&format=csv", headers=authorization(platform)))
        .headers["content-type"]
        .startswith("text/csv")
    )
    assert await CandidateRecord.find_all().count() == len(values)


async def test_settings_and_prompt_versions(platform):
    client, _, _ = platform
    headers = authorization(platform)
    assert (
        await client.put("/settings/thresholds", headers=headers, json={"semantic_weight": 0, "fault_weight": 0})
    ).status_code == 422
    assert (await client.put("/settings/llm", headers=headers, json={"provider": "gemini"})).status_code == 200
    settings = await SettingsRecord.get("pipeline")
    assert settings.pipeline.llm.generation_model.startswith("gemini")
    prompt = {"id": "gen_v1_admin1", "kind": "generation", "system": "Generate MRs", "user": "{{ api_context }}"}
    assert (await client.post("/prompts", headers=headers, json=prompt)).status_code == 201
    assert (await client.post("/prompts", headers=headers, json=prompt)).status_code == 409
    assert (await client.put("/prompts/gen_v1_admin1", headers=headers, json=prompt)).status_code == 409
    builtin = {**prompt, "id": "gen_v1"}
    assert (await client.post("/prompts", headers=headers, json=builtin)).status_code == 409


async def test_duplicate_active_run_is_rejected(platform, monkeypatch):
    async def held(*_):
        pass

    monkeypatch.setattr("app.api.execute_run", held)
    project = await create_project(platform)
    path = f"/projects/{project['id']}/runs"
    assert (await platform[0].post(path, headers=authorization(platform))).status_code == 202
    assert (await platform[0].post(path, headers=authorization(platform))).status_code == 409
    assert await RunRecord.find_all().count() == 1


async def test_admin_seed_is_idempotent_and_does_not_reset_existing_user(platform):
    from app.db import initialize_database

    _, app, _ = platform
    settings = app.state.settings.model_copy(update={"admin_email": "seed@example.com"})
    from pydantic import SecretStr

    settings.admin_password = SecretStr(PASSWORD)
    await initialize_database(settings, app.state.mongo)
    seed = await UserRecord.find_one(UserRecord.email == "seed@example.com")
    original_hash = seed.password_hash
    settings.admin_password = SecretStr("another-password-that-is-valid")
    await initialize_database(settings, app.state.mongo)
    seed = await UserRecord.find_one(UserRecord.email == "seed@example.com")
    assert seed.password_hash == original_hash
    assert await UserRecord.find(UserRecord.email == "seed@example.com").count() == 1


async def test_cors_uses_validated_configuration_and_openapi_has_output_schemas(platform):
    client, app, _ = platform
    app.state.settings.cors_origins = ["https://qa.example.com"]
    response = await client.options(
        "/projects",
        headers={
            "Origin": "https://qa.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers["access-control-allow-origin"] == "https://qa.example.com"
    schema = (await client.get("/openapi.json")).json()
    assert "UserOutput" in schema["components"]["schemas"]
    assert "password_hash" not in schema["components"]["schemas"]["UserOutput"]["properties"]
    assert "RunOutput" in schema["components"]["schemas"]


async def test_restart_reports_interrupted_run(platform, monkeypatch):
    async def held(*_):
        pass

    monkeypatch.setattr("app.api.execute_run", held)
    project = await create_project(platform)
    client, app, _ = platform
    created = await client.post(f"/projects/{project['id']}/runs", headers=authorization(platform))
    restarted = create_app(app.state.settings, mongo_client=app.state.mongo)
    async with restarted.router.lifespan_context(restarted):
        run = await RunRecord.get(created.json()["id"])
        assert run.status == "failed"
        assert "reinició" in run.report.error
