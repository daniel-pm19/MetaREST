"""Platform configuration; credentials are read from environment/.env only."""

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )
    mongodb_uri: SecretStr = SecretStr("mongodb://127.0.0.1:27017")
    mongodb_database: str = "metarest"
    jwt_secret: SecretStr
    jwt_expiration_minutes: int = Field(default=60, ge=1, le=1440)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    admin_email: str | None = None
    admin_password: SecretStr | None = None
    admin_name: str = "Administrador"
    fastembed_cache_dir: str = "../.fastembed_cache"
    max_spec_bytes: int = Field(default=2_000_000, ge=1024, le=10_000_000)

    @model_validator(mode="after")
    def validate_secrets(self):
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET debe tener al menos 32 caracteres")
        if bool(self.admin_email) != bool(self.admin_password):
            raise ValueError("ADMIN_EMAIL y ADMIN_PASSWORD deben configurarse juntos")
        return self
