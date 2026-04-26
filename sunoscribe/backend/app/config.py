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
    redis_url: str | None = None
    uploads_root: str = "data/uploads"
    max_media_duration_sec: float = 600.0
    upload_backend: str = "local"
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_secure: bool = False
    minio_region: str | None = None
    minio_base_path: str = "uploads"
    task_worker_count: int = 1
    pitch_backend: str = "rmvpe"
    pitch_backend_fallbacks: str = "crepe,basic-pitch"
    pitch_cache_dir: str = "~/.cache/sunoscribe/pitch"
    rmvpe_model_path: str | None = None

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

    @field_validator("upload_backend")
    @classmethod
    def _validate_upload_backend(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"local", "minio"}:
            raise ValueError("upload_backend must be one of: local, minio")
        return normalized

    @field_validator("pitch_backend")
    @classmethod
    def _validate_pitch_backend(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        aliases = {
            "basic_pitch": "basic-pitch",
            "basicpitch": "basic-pitch",
            "r-mvpe": "rmvpe",
            "rvc-rmvpe": "rmvpe",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"rmvpe", "crepe", "basic-pitch"}:
            raise ValueError("pitch_backend must be one of: rmvpe, crepe, basic-pitch")
        return normalized

    @field_validator("max_media_duration_sec")
    @classmethod
    def _validate_max_media_duration_sec(cls, value: float) -> float:
        normalized = float(value)
        if normalized <= 0:
            raise ValueError("max_media_duration_sec must be > 0")
        return normalized

    @field_validator("task_worker_count")
    @classmethod
    def _validate_task_worker_count(cls, value: int) -> int:
        normalized = int(value)
        if normalized < 1:
            raise ValueError("task_worker_count must be at least 1")
        return normalized

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
