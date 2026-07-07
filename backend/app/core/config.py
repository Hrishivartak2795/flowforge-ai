"""Application configuration.

Environment-driven, typed, and validated at startup. Prefer passing a ``Settings``
instance through the app factory over reading ``os.environ`` at module scope so
tests can override cleanly and misconfiguration fails fast.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings.

    Loaded from process env or a ``.env`` file (dev only). Names mirror
    ``.env.example``. Unknown keys are ignored so unrelated env vars are safe.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    environment: Literal["development", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Database (used from M0.4 onward; safe default for local dev)
    database_url: str = Field(default="postgresql+psycopg://flowforge:flowforge@db:5432/flowforge")

    # AI (populated in M4 / M5)
    anthropic_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency: process-wide singleton via ``lru_cache``.

    Override in tests with ``app.dependency_overrides[get_settings] = ...``.
    """
    return Settings()
