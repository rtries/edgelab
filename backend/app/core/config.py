"""Application settings, loaded from environment / .env.

Every service (API, Celery workers, Alembic) imports this one object so
configuration lives in exactly one place.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # environment
    api_env: str = "development"
    secret_key: str = "dev-only-change-me"

    # database
    database_url: str = "postgresql+asyncpg://edgelab:change-me@localhost:5432/edgelab"

    # redis / celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # CORS
    api_cors_origins: list[str] = ["http://localhost:3000"]

    # brokers / data (later phases)
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper: bool = True  # live trading stays off unless explicitly flipped
    polygon_api_key: str = ""

    # AI assistant
    anthropic_api_key: str = ""

    # Telegram bot (agent status/control from chat — see app/api/v1/telegram.py)
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""  # must match Telegram's X-Telegram-Bot-Api-Secret-Token

    # auth (Supabase-issued JWTs)
    # supabase_url enables JWKS-based verification (ES256/RS256) — the
    # default for current Supabase projects, and the primary path.
    supabase_url: str = ""
    # supabase_jwt_secret is a fallback for older projects still on the
    # legacy shared HS256 secret; optional if supabase_url is set.
    supabase_jwt_secret: str = ""
    auth_disabled: bool = False  # local dev / tests only — never true in prod

    @property
    def is_dev(self) -> bool:
        return self.api_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
