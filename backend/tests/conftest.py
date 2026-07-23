"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

# ── CLI option: --run-network ──
# Network-marked tests are deselected by default (addopts = -m 'not network').
# When explicitly included via ``pytest -m network``, they still need
# ``--run-network`` to actually run. This double-gate prevents accidental
# network calls in CI.

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests marked 'network' (require real internet access).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="needs --run-network to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


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
