"""Health endpoints.

``/health`` is a *liveness* probe (no dependencies — never fails due to a
downstream outage). ``/health/ready`` is a *readiness* probe that verifies the
database is reachable; it returns 503 when the DB is down so orchestrators
route traffic away without killing the process.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session

router = APIRouter(tags=["health"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class HealthResponse(BaseModel):
    """Response contract for the liveness probe."""

    status: str


class ReadinessResponse(BaseModel):
    """Response contract for the readiness probe."""

    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns HTTP 200 while the process is serving.

    Has zero external dependencies, so it never fails due to downstream outages.
    """
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(response: Response, session: DbSession) -> ReadinessResponse:
    """Readiness probe — 200 if the database answers, 503 otherwise."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="down")
    return ReadinessResponse(status="ok", database="up")
