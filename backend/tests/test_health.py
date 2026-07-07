"""Tests for the health endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """The liveness probe returns 200 with status 'ok'."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
