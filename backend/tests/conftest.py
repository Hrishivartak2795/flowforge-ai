"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    """Override settings for tests with sensible defaults (no external I/O)."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        log_level="WARNING",
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Create an isolated test app instance with test settings."""
    return create_app(settings=test_settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """FastAPI test client bound to the test app."""
    return TestClient(app)
