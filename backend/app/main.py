"""FastAPI entry point: uv run uvicorn app.main:app (single worker for the MVP)."""

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.auth import hash_password
from app.config import Settings
from app.db import initialize_database
from app.models.platform import RunRecord
from app.services import fail_run


class ConfiguredCORS:
    """Read validated origins after lifespan, instead of ignoring CORS_ORIGINS in .env."""

    def __init__(self, app, owner):
        self.app, self.owner = app, owner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cors = CORSMiddleware(
            self.app,
            allow_origins=self.owner.state.settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        await cors(scope, receive, send)


def create_app(settings: Settings | None = None, *, mongo_client=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings is None:
            from scripts._env import load_env

            load_env()
        app.state.settings = settings or Settings()
        app.state.embedders = {}
        app.state.dummy_password_hash = hash_password(secrets.token_urlsafe(24))
        client = await initialize_database(app.state.settings, mongo_client)
        app.state.mongo = client
        # BackgroundTasks do not survive a process restart. Make that visible to the UI.
        for run in await RunRecord.find(RunRecord.status == "running").to_list():
            await fail_run(run.id, "El servidor se reinició durante esta iteración; inicia una nueva")
        try:
            yield
        finally:
            if mongo_client is None:
                client.close()

    app = FastAPI(title="MetaREST", version="0.1.0", lifespan=lifespan)
    # JWT is validated server-side even when the frontend hides an action.
    app.add_middleware(ConfiguredCORS, owner=app)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # FastAPI's default response echoes input (including passwords/specs).
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()
                ]
            },
        )

    app.include_router(router)
    return app


app = create_app()
