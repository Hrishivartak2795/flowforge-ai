"""Tests for config loading and JSON logging."""

from __future__ import annotations

import json
import logging

import pytest

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.environment == "development"
    assert s.log_level == "INFO"
    assert s.embedding_model == "BAAI/bge-m3"


def test_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()  # bust the lru_cache singleton
    s = get_settings()
    assert s.environment == "production"
    assert s.log_level == "WARNING"
    get_settings.cache_clear()


def test_json_logging_emits_valid_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    logging.getLogger("flowforge.test").info("hello", extra={"run_id": "abc"})
    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "flowforge.test"
    assert payload["run_id"] == "abc"
