"""FastAPI application factory and module-level ASGI instance."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown: create the DB engine on boot, dispose it on shutdown."""
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    logger.info("app.startup", extra={"environment": settings.environment})
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("app.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Settings can be injected (useful in tests); otherwise the process-wide
    singleton from :func:`get_settings` is used. The database engine/session
    factory are created in the lifespan handler and stored on ``app.state``.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="FlowForge AI",
        version="0.1.0",
        summary="AI-Powered Requirements Intelligence & Engineering Decision Platform",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(health.router)
    return app


app = create_app()
