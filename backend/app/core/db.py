"""Database engine, session factory, and the FastAPI session dependency.

Async SQLAlchemy 2.x over the psycopg (v3) async driver. The engine is created
once per process; a per-request ``AsyncSession`` is yielded via
:func:`get_db_session` so routes/services never construct their own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the process-wide async engine from settings.

    ``pool_pre_ping`` avoids handing out dead connections after a DB restart —
    cheap insurance that matters once analyses run for minutes.
    """
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Build a session factory bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a request-scoped ``AsyncSession``.

    The session factory lives on ``app.state`` (wired in the app factory), so
    this dependency has no module-level globals and is trivially overridable in
    tests via ``app.dependency_overrides``.
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
