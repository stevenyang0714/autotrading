"""Data Health API (M0.3): source registry, freshness, ingestion runs and dead letters.

Read-only. The Data Health page (M0.4) renders these through the glossary <Metric> component.
"""

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, sessionmaker

from autotrading.db.models import DeadLetter, IngestionRun, Source
from autotrading.domain.freshness import FreshnessStatus, freshness_status

router = APIRouter(tags=["data health"])

FAILED_STATUSES = ("failed", "dead_lettered")
FINISHED_STATUSES = ("succeeded", *FAILED_STATUSES)


def get_session(request: Request) -> Iterator[Session]:
    sessions: sessionmaker[Session] | None = getattr(request.app.state, "sessions", None)
    if sessions is None:
        raise HTTPException(status_code=503, detail="database session factory not configured")
    with sessions() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: str
    job: str
    params: dict[str, Any]
    window_start: datetime | None
    window_end: datetime | None
    status: str
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    rows_inserted: int
    rows_unchanged: int
    raw_payload_keys: list[str]
    error_class: str | None
    error_message: str | None
    created_at: datetime


class DeadLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ingestion_run_id: UUID
    source_id: str
    job: str
    params: dict[str, Any]
    attempts: int
    error_class: str | None
    error_message: str | None
    failed_at: datetime
    resolved_at: datetime | None
    resolution: str | None


class SourceHealth(BaseModel):
    id: str
    name: str
    url: str
    tier: int
    license_status: str
    access_status: str
    enabled: bool
    update_cadence: str
    freshness_sla_seconds: int
    rate_limit_per_second: Decimal
    rate_limit_burst: int
    topics: list[str]
    freshness: FreshnessStatus | None  # None = disabled, not judged
    last_success_at: datetime | None
    last_run: RunOut | None
    open_dead_letters: int


class DataHealthReport(BaseModel):
    checked_at: datetime
    sources: list[SourceHealth]


@router.get("/data-health")
def data_health(session: SessionDep) -> DataHealthReport:
    now: datetime = session.execute(select(func.now())).scalar_one()
    sources = session.scalars(select(Source).order_by(Source.priority, Source.id)).all()

    last_success = dict(
        session.execute(
            select(IngestionRun.source_id, func.max(IngestionRun.finished_at))
            .where(IngestionRun.status == "succeeded")
            .group_by(IngestionRun.source_id)
        ).all()
    )
    latest_finished = {
        source_id: status
        for source_id, status in session.execute(
            select(IngestionRun.source_id, IngestionRun.status)
            .where(IngestionRun.status.in_(FINISHED_STATUSES))
            .ext(distinct_on(IngestionRun.source_id))
            .order_by(IngestionRun.source_id, IngestionRun.finished_at.desc())
        ).all()
    }
    last_runs = {
        run.source_id: run
        for run in session.scalars(
            select(IngestionRun)
            .ext(distinct_on(IngestionRun.source_id))
            .order_by(IngestionRun.source_id, IngestionRun.created_at.desc())
        )
    }
    open_dead_letters = dict(
        session.execute(
            select(DeadLetter.source_id, func.count())
            .where(DeadLetter.resolved_at.is_(None))
            .group_by(DeadLetter.source_id)
        ).all()
    )

    report = []
    for source in sources:
        last_run = last_runs.get(source.id)
        report.append(
            SourceHealth(
                id=source.id,
                name=source.name,
                url=source.url,
                tier=source.tier,
                license_status=source.license_status,
                access_status=source.access_status,
                enabled=source.enabled,
                update_cadence=source.update_cadence,
                freshness_sla_seconds=source.freshness_sla_seconds,
                rate_limit_per_second=source.rate_limit_per_second,
                rate_limit_burst=source.rate_limit_burst,
                topics=source.topics,
                freshness=freshness_status(
                    now=now,
                    enabled=source.enabled,
                    sla_seconds=source.freshness_sla_seconds,
                    last_success_at=last_success.get(source.id),
                    last_attempt_failed=latest_finished.get(source.id) in FAILED_STATUSES,
                ),
                last_success_at=last_success.get(source.id),
                last_run=RunOut.model_validate(last_run) if last_run else None,
                open_dead_letters=open_dead_letters.get(source.id, 0),
            )
        )
    return DataHealthReport(checked_at=now, sources=report)


@router.get("/ingestion-runs")
def ingestion_runs(
    session: SessionDep,
    source_id: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunOut]:
    query = select(IngestionRun).order_by(IngestionRun.created_at.desc()).limit(limit)
    if source_id is not None:
        query = query.where(IngestionRun.source_id == source_id)
    if status is not None:
        query = query.where(IngestionRun.status == status)
    return [RunOut.model_validate(run) for run in session.scalars(query)]


@router.get("/dead-letters")
def dead_letters(
    session: SessionDep,
    unresolved: bool = True,
    source_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DeadLetterOut]:
    query = select(DeadLetter).order_by(DeadLetter.failed_at.desc()).limit(limit)
    if unresolved:
        query = query.where(DeadLetter.resolved_at.is_(None))
    if source_id is not None:
        query = query.where(DeadLetter.source_id == source_id)
    return [DeadLetterOut.model_validate(row) for row in session.scalars(query)]
