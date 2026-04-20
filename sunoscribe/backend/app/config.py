import secrets

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SunoScribe Backend"
    api_prefix: str = "/api"
    app_env: str = "development"
    expose_internal_errors: bool = False

    # Use a strong random key by default to avoid predictable JWT secrets.
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # PRD 要求 PostgreSQL；默认值可通过 .env 覆盖。
    # Avoid committing hard-coded credentials in code.
    database_url: str = "postgresql+psycopg://localhost:5432/sunoscribe"

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        normalized = (value or "").strip()
        if len(normalized) < 32:
            raise ValueError("secret_key must be at least 32 characters")
        return normalized

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
