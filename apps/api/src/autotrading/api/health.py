"""Health endpoints.

- GET /health/live: the API process is up. Used by the container healthcheck, so it
  must not depend on anything else.
- GET /health: dependency status. Any core dependency down -> 503. Late worker or
  scheduler heartbeats -> 200 with status "degraded"; they never make the API red.
"""

from datetime import UTC, datetime
from typing import Literal, Protocol

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from autotrading.infra.probes import ProbeResult, ProbeStatus

OverallStatus = Literal["ok", "degraded", "down"]


class HealthChecker(Protocol):
    def core(self) -> dict[str, ProbeResult]: ...

    def background(self) -> dict[str, ProbeResult]: ...


class ComponentHealth(BaseModel):
    status: ProbeStatus
    latency_ms: float
    detail: str | None


class HealthReport(BaseModel):
    status: OverallStatus
    checked_at: datetime
    components: dict[str, ComponentHealth]


def overall_status(
    core: dict[str, ProbeResult], background: dict[str, ProbeResult]
) -> OverallStatus:
    if any(result.status != "ok" for result in core.values()):
        return "down"
    if any(result.status != "ok" for result in background.values()):
        return "degraded"
    return "ok"


router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", responses={503: {"model": HealthReport}})
def health(request: Request, response: Response) -> HealthReport:
    checker: HealthChecker = request.app.state.health_checker
    core = checker.core()
    background = checker.background()
    status = overall_status(core, background)
    if status == "down":
        response.status_code = 503
    return HealthReport(
        status=status,
        checked_at=datetime.now(UTC),
        components={
            name: ComponentHealth(
                status=result.status, latency_ms=result.latency_ms, detail=result.detail
            )
            for name, result in {**core, **background}.items()
        },
    )
