"""Health endpoints.

``/health`` is a *liveness* probe: it answers "is the process up and
serving?" with **no** external dependencies, so it never fails because of a
downstream outage. A *readiness* probe (``/health/ready``) that checks the
database is added in Milestone 0.4 — kept separate on purpose, so a transient
database blip cannot make the liveness probe report the process as dead.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response contract for the liveness probe."""

    status: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns HTTP 200 while the process is serving."""
    return HealthResponse(status="ok")
