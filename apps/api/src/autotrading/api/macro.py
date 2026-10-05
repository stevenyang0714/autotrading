"""Macro API (M0.6): the FRED series registry and observations as known at a time.

Values come from `as_of(known_at)` over macro_observations (ADR-012, ADR-015): each date shows
the latest vintage published by then, plus the first release when it was revised since.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from autotrading.api.data_health import SessionDep
from autotrading.db.models import IngestionRun, MacroObservation, MacroSeries
from autotrading.repositories.facts import as_of_query

router = APIRouter(tags=["macro"])

FRED_SOURCE = "fred"


class SeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    term_id: str
    title: str | None
    units: str | None
    units_short: str | None
    frequency: str | None
    seasonal_adjustment_short: str | None
    last_updated: datetime | None


class FirstRelease(BaseModel):
    value: Decimal
    vintage: date


class ObservationOut(BaseModel):
    observation_date: date
    period_end: date | None
    value: Decimal
    vintage: date
    published_at: datetime
    published_at_precision: str
    source_url: str
    revised: bool  # a later vintage changed the first-released value (as known then)
    first_release: FirstRelease | None


class SeriesSummary(BaseModel):
    series: SeriesOut
    latest: ObservationOut | None


class MacroSeriesList(BaseModel):
    series: list[SeriesSummary]
    last_refresh_at: datetime | None


class SeriesObservations(BaseModel):
    series: SeriesOut
    known_at: datetime
    observations: list[ObservationOut]  # newest observation date first
    last_refresh_at: datetime | None


@router.get("/macro/series")
def list_series(session: SessionDep) -> MacroSeriesList:
    now: datetime = session.execute(select(func.now())).scalar_one()
    rows = session.scalars(
        select(MacroSeries)
        .where(MacroSeries.enabled.is_(True))
        .order_by(MacroSeries.position, MacroSeries.id)
    ).all()
    return MacroSeriesList(
        series=[
            SeriesSummary(
                series=SeriesOut.model_validate(row),
                latest=next(iter(_observations(session, row.id, now, limit=1)), None),
            )
            for row in rows
        ],
        last_refresh_at=_last_refresh(session),
    )


@router.get("/macro/series/{series_id}/observations")
def series_observations(
    series_id: str,
    session: SessionDep,
    known_at: Annotated[
        AwareDatetime | None, Query(description="Point in time (ADR-012); default now")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=240)] = 24,
) -> SeriesObservations:
    row = session.get(MacroSeries, series_id.upper())
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown macro series {series_id!r}")
    at: datetime = known_at or session.execute(select(func.now())).scalar_one()
    return SeriesObservations(
        series=SeriesOut.model_validate(row),
        known_at=at,
        observations=_observations(session, row.id, at, limit=limit),
        last_refresh_at=_last_refresh(session),
    )


def _observations(
    session: Session, series_id: str, known_at: datetime, *, limit: int
) -> list[ObservationOut]:
    """The latest `limit` observation dates, each as known at `known_at`."""
    known = as_of_query(MacroObservation, known_at=known_at).where(
        MacroObservation.series_id == series_id
    )
    shown = aliased(MacroObservation, known.subquery())
    rows = session.scalars(select(shown).order_by(shown.observation_date.desc()).limit(limit)).all()
    if not rows:
        return []
    first = {
        obs.observation_date: obs
        for obs in session.scalars(
            select(MacroObservation)
            .where(
                MacroObservation.series_id == series_id,
                MacroObservation.observation_date.in_([r.observation_date for r in rows]),
                MacroObservation.published_at <= known_at,
                MacroObservation.superseded_at.is_(None),
            )
            .ext(distinct_on(MacroObservation.observation_date))
            .order_by(MacroObservation.observation_date, MacroObservation.published_at)
        )
    }
    out = []
    for obs in rows:
        earliest = first.get(obs.observation_date)
        revised = earliest is not None and earliest.id != obs.id
        out.append(
            ObservationOut(
                observation_date=obs.observation_date,
                period_end=obs.effective_to.date() if obs.effective_to else None,
                value=obs.value,
                vintage=obs.vintage,
                published_at=obs.published_at,
                published_at_precision=obs.published_at_precision,
                source_url=obs.source_url,
                revised=revised,
                first_release=(
                    FirstRelease(value=earliest.value, vintage=earliest.vintage)
                    if revised and earliest is not None
                    else None
                ),
            )
        )
    return out


def _last_refresh(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(IngestionRun.finished_at)).where(
            IngestionRun.source_id == FRED_SOURCE, IngestionRun.status == "succeeded"
        )
    )
