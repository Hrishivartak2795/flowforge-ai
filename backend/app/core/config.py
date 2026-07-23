"""Application configuration.

Environment-driven, typed, and validated at startup. Prefer passing a ``Settings``
instance through the app factory over reading ``os.environ`` at module scope so
tests can override cleanly and misconfiguration fails fast.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_parse_workers() -> int:
    return min(4, os.cpu_count() or 1)


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

    # Ingestion (used from M2 onward)
    #
    # ``uploads_dir`` is a *local* staging area for extracted archives and
    # cloned repositories. It is per-container ephemeral; nothing durable lives
    # here (the DB is the source of truth). Size and file-count caps below are
    # first-line defenses against zip bombs and archive DoS — the ZIP extractor
    # refuses anything above these thresholds *before* writing to disk.
    uploads_dir: Path = Field(default=Path("/tmp/flowforge/uploads"))
    max_repo_bytes: int = Field(default=200 * 1024 * 1024)  # 200 MiB uncompressed
    max_files_per_repo: int = Field(default=20_000)
    clone_timeout_seconds: int = Field(default=120)
    # M2 Step 3 — per-file size cap during discovery. Oversized files are
    # skipped-and-logged, not fatal; this bounds parser input size independently
    # of the archive-level `max_repo_bytes` cumulative cap.
    max_file_bytes: int = Field(default=1_048_576)  # 1 MiB
    # M2 Step 8 — bounded process-pool size for concurrent per-file AST parsing.
    ingestion_parse_workers: int = Field(default_factory=_default_parse_workers, ge=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency: process-wide singleton via ``lru_cache``.

    Override in tests with ``app.dependency_overrides[get_settings] = ...``.
    """
    return Settings()
