"""FastAPI application factory. Run with `uvicorn autotrading.main:app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from autotrading.api.health import HealthChecker
from autotrading.api.health import router as health_router
from autotrading.infra.dependencies import Dependencies
from autotrading.infra.object_store import ensure_bucket
from autotrading.settings import get_settings

logger = logging.getLogger(__name__)


def create_app(health_checker: HealthChecker | None = None) -> FastAPI:
    """Build the app. Tests pass a fake `health_checker`; otherwise live connections are used."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if health_checker is not None:
            app.state.health_checker = health_checker
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
        try:
            yield
        finally:
            deps.close()

    app = FastAPI(title="Global Market Intelligence API", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()
