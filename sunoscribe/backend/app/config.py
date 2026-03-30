from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SunoScribe Backend"
    api_prefix: str = "/api"

    secret_key: str = "change-this-in-env"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # PRD 要求 PostgreSQL；默认值可通过 .env 覆盖
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/sunoscribe"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
