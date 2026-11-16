"""Mongo initialization and idempotent initial administrator seed."""

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import EmailStr, TypeAdapter

from app.config import Settings
from app.models.platform import DOCUMENTS, Role, SettingsRecord, UserRecord


async def initialize_database(settings: Settings, client=None):
    client = (
        client
        if client is not None
        else AsyncIOMotorClient(
            settings.mongodb_uri.get_secret_value(),
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
        )
    )
    await client.admin.command("ping")
    await init_beanie(database=client[settings.mongodb_database], document_models=DOCUMENTS)
    if await SettingsRecord.get("pipeline") is None:
        await SettingsRecord().insert()
    if settings.admin_email:
        from app.auth import hash_password

        email = str(TypeAdapter(EmailStr).validate_python(settings.admin_email)).lower()
        if await UserRecord.find_one(UserRecord.email == email) is None:
            await UserRecord(
                name=settings.admin_name,
                email=email,
                role=Role.ADMIN,
                password_hash=hash_password(settings.admin_password.get_secret_value()),
            ).insert()
    return client
