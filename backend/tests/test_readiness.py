"""Tests for the readiness probe using dependency overrides (no real DB)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db_session


class _OkSession:
    async def execute(self, *args: object, **kwargs: object) -> object:
        return None


class _BrokenSession:
    async def execute(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("db down")


async def _ok_session() -> AsyncIterator[_OkSession]:
    yield _OkSession()


async def _broken_session() -> AsyncIterator[_BrokenSession]:
    yield _BrokenSession()


def test_readiness_ok_when_db_answers(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_db_session] = _ok_session
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_readiness_503_when_db_down(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_db_session] = _broken_session
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "down"}
