"""FastAPI application factory. Run with `uvicorn autotrading.main:app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from autotrading.api.data_health import router as data_health_router
from autotrading.api.glossary import router as glossary_router
from autotrading.api.health import HealthChecker
from autotrading.api.health import router as health_router
from autotrading.api.instruments import router as instruments_router
from autotrading.infra.dependencies import Dependencies
from autotrading.infra.object_store import ensure_bucket
from autotrading.settings import get_settings

logger = logging.getLogger(__name__)


def create_app(
    health_checker: HealthChecker | None = None,
    sessions: sessionmaker[Session] | None = None,
) -> FastAPI:
    """Build the app. Tests pass fakes / a test database; otherwise live connections are used."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if health_checker is not None:
            app.state.health_checker = health_checker
            app.state.sessions = sessions
            yield
            return

        # Loading settings here also enforces the live-trading guard (ADR-008).
        settings = get_settings()
        deps = Dependencies.from_settings(settings)
        try:
            ensure_bucket(deps.s3, settings.s3_bucket)
        except Exception as exc:
            # Startup continues; /health reports object_store as down.
            logger.warning("Could not ensure bucket %s: %s", settings.s3_bucket, type(exc).__name__)
        app.state.health_checker = deps
        app.state.sessions = sessions or sessionmaker(deps.engine)
        try:
            yield
        finally:
            deps.close()

    app = FastAPI(title="Global Market Intelligence API", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(data_health_router)
    app.include_router(glossary_router)
    app.include_router(instruments_router)
    return app


app = create_app()
