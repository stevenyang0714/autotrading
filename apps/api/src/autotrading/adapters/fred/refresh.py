"""FRED refresh orchestration (M0.6): one `fred.series` run per enabled registry series, in one
refresh window (ingestion/schedule.py). Scheduled daily at 10:15 SGT, after SEC."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.fred.series import SOURCE_ID, FredSeriesJob
from autotrading.db.models import MacroSeries, Source
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window

REFRESH_HOUR, REFRESH_MINUTE = 10, 15


def enabled_series(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(MacroSeries.id)
            .where(MacroSeries.enabled.is_(True))
            .order_by(MacroSeries.position, MacroSeries.id)
        )
    )


def start_refresh(runner: IngestionRunner, *, now: datetime, manual: bool) -> list[UUID]:
    """Create the runs; empty when the source is disabled or no series is enabled."""
    with runner.sessions() as session:
        source = session.get(Source, SOURCE_ID)
        if source is None or not source.enabled:
            return []
        series = enabled_series(session)
    window = refresh_window(now, manual=manual)
    return [runner.create_run(FredSeriesJob.name, {"series_id": s}, window) for s in series]
