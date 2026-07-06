"""FlowForge backend entrypoint.

Exposes an application factory (:func:`create_app`) plus a module-level
``app`` instance for ASGI servers (uvicorn) to import as ``app.main:app``.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import health


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    A factory (rather than a module-level global built inline) keeps
    construction explicit and testable: tests can build an isolated app
    instance, and future wiring — configuration, database sessions,
    middleware, additional routers — has a single, obvious home here.
    """
    app = FastAPI(
        title="FlowForge AI",
        version="0.1.0",
        summary="AI-Powered Requirements Intelligence & Engineering Decision Platform",
    )
    app.include_router(health.router)
    return app


# Module-level instance for ASGI servers: `uvicorn app.main:app`.
app = create_app()
