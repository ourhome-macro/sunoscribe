import secrets

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SunoScribe Backend"
    api_prefix: str = "/api"
    app_env: str = "development"
    expose_internal_errors: bool = False

    secret_key: str | None = None
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    redis_url: str | None = None
    api_keys_encryption_key: str | None = None
    password_reset_base_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
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
    task_stale_after_minutes: int = 120
    task_timeout_seconds: int = 1800
    canonical_audio_sample_rate: int = 44100
    canonical_audio_channels: int = 2
    pitch_backend: str = "rmvpe"
    pitch_profile: str = "production"
    pitch_allow_backend_fallbacks: bool = False
    pitch_backend_fallbacks: str = ""
    pitch_cache_dir: str = "~/.cache/sunoscribe/pitch"
    rmvpe_model_path: str | None = None
    openai_api_key: str | None = None
    agent_llm_enabled: bool = False
    agent_llm_provider: str = "openai"
    agent_llm_model: str = "gpt-5.4-mini"
    rvc_endpoint_url: str | None = None
    rvc_api_key: str | None = None
    rvc_request_timeout_seconds: int = 600

    # PRD 瑕佹眰 PostgreSQL锛涢粯璁ゅ€煎彲閫氳繃 .env 瑕嗙洊銆?
    # Avoid committing hard-coded credentials in code.
    database_url: str = "postgresql+psycopg://localhost:5432/sunoscribe"

    @field_validator("app_env")
    @classmethod
    def _validate_app_env(cls, value: str) -> str:
        return str(value or "development").strip().lower()

    @field_validator("secret_key", "api_keys_encryption_key")
    @classmethod
    def _strip_secret_value(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

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

    @field_validator("pitch_profile")
    @classmethod
    def _validate_pitch_profile(cls, value: str) -> str:
        normalized = (value or "production").strip().lower()
        if normalized not in {"production", "diagnostic", "benchmark"}:
            raise ValueError("pitch_profile must be one of: production, diagnostic, benchmark")
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

    @field_validator("canonical_audio_sample_rate", "canonical_audio_channels")
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        normalized = int(value)
        if normalized < 1:
            raise ValueError("audio configuration values must be positive integers")
        return normalized

    @field_validator("agent_llm_provider")
    @classmethod
    def _validate_agent_llm_provider(cls, value: str) -> str:
        normalized = str(value or "openai").strip().lower()
        if normalized not in {"openai"}:
            raise ValueError("agent_llm_provider must be openai")
        return normalized

    @field_validator("agent_llm_model")
    @classmethod
    def _validate_agent_llm_model(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("agent_llm_model must not be empty")
        return normalized

    @field_validator("task_stale_after_minutes")
    @classmethod
    def _validate_task_stale_after_minutes(cls, value: int) -> int:
        normalized = int(value)
        if normalized < 1:
            raise ValueError("task_stale_after_minutes must be at least 1")
        return normalized

    @field_validator("task_timeout_seconds")
    @classmethod
    def _validate_task_timeout_seconds(cls, value: int) -> int:
        normalized = int(value)
        if normalized < 1:
            raise ValueError("task_timeout_seconds must be at least 1")
        return normalized

    @field_validator("rvc_endpoint_url", "rvc_api_key")
    @classmethod
    def _strip_optional_rvc_value(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("rvc_request_timeout_seconds")
    @classmethod
    def _validate_rvc_request_timeout_seconds(cls, value: int) -> int:
        normalized = int(value)
        if normalized < 1:
            raise ValueError("rvc_request_timeout_seconds must be at least 1")
        return normalized

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        if not self.secret_key:
            if self.app_env == "production":
                raise ValueError("secret_key must be configured in production")
            self.secret_key = secrets.token_urlsafe(48)
        elif len(self.secret_key) < 32:
            raise ValueError("secret_key must be at least 32 characters")

        if not self.api_keys_encryption_key:
            if self.app_env == "production":
                raise ValueError("api_keys_encryption_key must be configured in production")
            self.api_keys_encryption_key = secrets.token_urlsafe(48)
        elif len(self.api_keys_encryption_key) < 32:
            raise ValueError("api_keys_encryption_key must be at least 32 characters")

        if self.app_env == "production":
            missing_password_reset = [
                name
                for name, value in {
                    "redis_url": self.redis_url,
                    "password_reset_base_url": self.password_reset_base_url,
                    "smtp_host": self.smtp_host,
                    "smtp_from_email": self.smtp_from_email,
                }.items()
                if not str(value or "").strip()
            ]
            if missing_password_reset:
                joined = ", ".join(missing_password_reset)
                raise ValueError(f"password reset production config missing: {joined}")

        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()

