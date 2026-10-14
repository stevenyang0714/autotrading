"""Alpaca refresh orchestration (M0.7, ADR-017): which runs to create, without the broker.

- Snapshots: one run per minute while the US market is open, plus the minutes just after the
  close (to keep the closing quote). The run window is that minute, so a repeated trigger in
  the same minute is skipped.
- Daily bars: the last weeks of raw and split-adjusted bars once a day (06:30 SGT), or the full
  history since 2016 for a backfill.
- Splits: the universe's splits since 2016, queued with the daily bars (M1.1; ETFs since M2.2).
- Dividends: the universe's cash dividends since 2016, queued with the daily bars (M2.2).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy.orm import Session

from autotrading.adapters.alpaca.bars import BACKFILL_START, AlpacaDailyBarsJob
from autotrading.adapters.alpaca.client import configured
from autotrading.adapters.alpaca.dividends import AlpacaDividendsJob
from autotrading.adapters.alpaca.snapshots import AlpacaSnapshotsJob
from autotrading.adapters.alpaca.splits import HISTORY_START, AlpacaSplitsJob
from autotrading.adapters.alpaca.symbols import SOURCE_ID
from autotrading.db.models import Source
from autotrading.domain.market_calendar import MarketCalendar
from autotrading.ingestion.job import Window
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window

AFTER_CLOSE = timedelta(minutes=3)
DAILY_LOOKBACK = timedelta(days=21)  # about 15 sessions: covers a missed day or two


def universe(config_dir: Path) -> tuple[list[str], list[str]]:
    """(all symbols, ETFs) from config/universe.yaml."""
    data = yaml.safe_load((config_dir / "universe.yaml").read_text(encoding="utf-8"))
    equities = [str(s).upper() for s in data.get("equities") or []]
    etfs = [str(s).upper() for s in data.get("etfs") or []]
    return equities + etfs, etfs


def source_ready(session: Session) -> bool:
    source = session.get(Source, SOURCE_ID)
    return source is not None and source.enabled and configured()


def in_snapshot_hours(calendar: MarketCalendar, now: datetime) -> bool:
    return calendar.is_open(now) or now - calendar.last_close(now) <= AFTER_CLOSE


def start_snapshots(
    runner: IngestionRunner,
    *,
    now: datetime,
    calendar: MarketCalendar,
    config_dir: Path,
    force: bool = False,
) -> UUID | None:
    """The run for this minute, or None outside snapshot hours (unless forced) or when the
    source is disabled or has no keys."""
    with runner.sessions() as session:
        if not source_ready(session):
            return None
    if not force and not in_snapshot_hours(calendar, now):
        return None
    minute = now.astimezone(UTC).replace(second=0, microsecond=0)
    symbols, etfs = universe(config_dir)
    window = Window(start=minute, end=minute + timedelta(minutes=1))
    return runner.create_run(AlpacaSnapshotsJob.name, {"symbols": symbols, "etfs": etfs}, window)


def start_daily_bars(
    runner: IngestionRunner,
    *,
    now: datetime,
    manual: bool,
    config_dir: Path,
    backfill: bool = False,
) -> UUID | None:
    with runner.sessions() as session:
        if not source_ready(session):
            return None
    symbols, etfs = universe(config_dir)
    start = BACKFILL_START if backfill else (now.date() - DAILY_LOOKBACK).isoformat()
    return runner.create_run(
        AlpacaDailyBarsJob.name,
        {"symbols": symbols, "etfs": etfs, "start": start},
        refresh_window(now, manual=manual or backfill),
    )


def start_splits(
    runner: IngestionRunner, *, now: datetime, manual: bool, config_dir: Path
) -> UUID | None:
    with runner.sessions() as session:
        if not source_ready(session):
            return None
    symbols, _ = universe(config_dir)
    return runner.create_run(
        AlpacaSplitsJob.name,
        {"symbols": symbols, "start": HISTORY_START},
        refresh_window(now, manual=manual),
    )


def start_dividends(
    runner: IngestionRunner, *, now: datetime, manual: bool, config_dir: Path
) -> UUID | None:
    with runner.sessions() as session:
        if not source_ready(session):
            return None
    symbols, _ = universe(config_dir)
    return runner.create_run(
        AlpacaDividendsJob.name,
        {"symbols": symbols, "start": HISTORY_START},
        refresh_window(now, manual=manual),
    )
