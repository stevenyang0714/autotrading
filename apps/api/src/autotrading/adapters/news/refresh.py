"""News refresh orchestration (M0.8, ADR-018): which runs to create, without the broker.

- GDELT: one run per hour (the hour slot is the idempotency window), searching the last 24
  hours for every configured equity; a backfill makes one run per UTC day.
- Feeds: one run per enabled feed every 30 minutes, with If-Modified-Since set to when the
  newest stored item of that feed was fetched (none stored: a full fetch).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autotrading.adapters.news.config import entities, feeds
from autotrading.adapters.news.gdelt import MAX_RECORDS, SOURCE_ID, GdeltJob, gdelt_time
from autotrading.adapters.news.rss import job_name
from autotrading.db.models import NewsItem, Source
from autotrading.ingestion.job import Window
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import GDELT, NEWS_FEEDS, IntervalSchedule

GDELT_LOOKBACK = timedelta(hours=24)
BACKFILL_DAYS = 14


def enabled_sources(session: Session, source_ids: list[str]) -> set[str]:
    return set(session.scalars(select(Source.id).where(Source.id.in_(source_ids), Source.enabled)))


def _window(schedule: IntervalSchedule, now: datetime, manual: bool) -> Window:
    slot = schedule.slot(now)
    return Window(start=slot.start, end=now.astimezone(UTC)) if manual else slot


def gdelt_params(start: datetime, end: datetime) -> dict[str, object]:
    return {
        "tickers": sorted(entities().companies),
        "start": gdelt_time(start),
        "end": gdelt_time(end),
        "maxrecords": MAX_RECORDS,
    }


def start_gdelt(runner: IngestionRunner, *, now: datetime, manual: bool) -> UUID | None:
    """This hour's GDELT run, or None when GDELT is disabled."""
    with runner.sessions() as session:
        if not enabled_sources(session, [SOURCE_ID]):
            return None
    # Start from another equity each hour, so a throttled run does not always miss the same ones.
    params = {**gdelt_params(now - GDELT_LOOKBACK, now), "rotate": now.astimezone(UTC).hour}
    return runner.create_run(GdeltJob.name, params, _window(GDELT, now, manual))


def start_gdelt_backfill(
    runner: IngestionRunner, *, now: datetime, days: int = BACKFILL_DAYS
) -> list[UUID]:
    """One GDELT run per UTC day over the last `days` days (GDELT keeps about three months)."""
    with runner.sessions() as session:
        if not enabled_sources(session, [SOURCE_ID]):
            return []
    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    run_ids = []
    for back in range(days, -1, -1):
        start = today - timedelta(days=back)
        end = min(start + timedelta(days=1), now.astimezone(UTC))
        run_ids.append(
            runner.create_run(GdeltJob.name, gdelt_params(start, end), Window(start=start, end=end))
        )
    return run_ids


def start_feeds(runner: IngestionRunner, *, now: datetime, manual: bool) -> list[UUID]:
    """One run per enabled feed for this half-hour slot."""
    configured = feeds()
    with runner.sessions() as session:
        enabled = enabled_sources(session, list(configured))
        last_fetch = dict(
            session.execute(
                select(NewsItem.source_id, func.max(NewsItem.ingested_at))
                .where(NewsItem.source_id.in_(list(enabled)))
                .group_by(NewsItem.source_id)
            ).all()
        )
    window = _window(NEWS_FEEDS, now, manual)
    run_ids = []
    for source_id in sorted(enabled):
        since = last_fetch.get(source_id)
        params = {"if_modified_since": since.isoformat()} if since else {}
        run_ids.append(runner.create_run(job_name(source_id), params, window))
    return run_ids
