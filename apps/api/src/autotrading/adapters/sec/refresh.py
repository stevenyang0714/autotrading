"""SEC refresh orchestration (M0.5): which runs to create, without touching the broker.

A refresh is one `sec.tickers` run followed, once it succeeds, by one `sec.company` run per
universe equity. All runs share a window, which is part of their idempotency key:
- scheduled (daily 10:00 SGT): the Singapore calendar day, so a repeated trigger the same day
  is skipped;
- manual (`make sec-refresh`): from the start of that day to now, so it always runs.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.sec.company import SecCompanyJob
from autotrading.adapters.sec.tickers import NAMESPACE, SOURCE_ID, SecTickersJob
from autotrading.db.models import Identifier, IngestionRun, Instrument, Source
from autotrading.ingestion.job import Window
from autotrading.ingestion.runner import IngestionRunner

REFRESH_TIMEZONE = ZoneInfo("Asia/Singapore")
REFRESH_HOUR = 10


def refresh_window(now: datetime, *, manual: bool) -> Window:
    day_start = now.astimezone(REFRESH_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day_start.astimezone(UTC)
    end = now.astimezone(UTC) if manual else (day_start + timedelta(days=1)).astimezone(UTC)
    return Window(start=start, end=end)


def universe_equities(config_dir: Path) -> list[str]:
    data = yaml.safe_load((config_dir / "universe.yaml").read_text(encoding="utf-8"))
    return sorted({str(ticker).upper() for ticker in data.get("equities") or []})


def source_enabled(session: Session) -> bool:
    source = session.get(Source, SOURCE_ID)
    return source is not None and source.enabled


def company_ciks(session: Session, tickers: list[str]) -> list[str]:
    """CIKs behind the universe tickers, from the identifiers `sec.tickers` maintains."""
    ticker_id = Identifier.__table__.alias("ticker_id")
    cik_id = Identifier.__table__.alias("cik_id")
    query = (
        select(cik_id.c.id_value)
        .select_from(ticker_id)
        .join(Instrument, Instrument.id == ticker_id.c.instrument_id)
        .join(cik_id, cik_id.c.entity_id == Instrument.entity_id)
        .where(
            ticker_id.c.id_type == "ticker",
            ticker_id.c.id_namespace == NAMESPACE,
            ticker_id.c.id_value.in_(tickers),
            ticker_id.c.valid_to.is_(None),
            cik_id.c.id_type == "cik",
            cik_id.c.id_namespace == NAMESPACE,
            cik_id.c.valid_to.is_(None),
        )
        .distinct()
        .order_by(cik_id.c.id_value)
    )
    return list(session.scalars(query))


def start_refresh(
    runner: IngestionRunner, *, now: datetime, manual: bool, config_dir: Path
) -> UUID | None:
    """Create the `sec.tickers` run, or None when the source is not enabled."""
    with runner.sessions() as session:
        if not source_enabled(session):
            return None
    return runner.create_run(
        SecTickersJob.name,
        {"tickers": universe_equities(config_dir)},
        refresh_window(now, manual=manual),
    )


def create_company_runs(runner: IngestionRunner, tickers_run_id: UUID) -> list[UUID]:
    """One `sec.company` run per CIK, in the window of the tickers run that preceded it."""
    with runner.sessions() as session:
        run = session.get_one(IngestionRun, tickers_run_id)
        window = Window(start=run.window_start, end=run.window_end)
        ciks = company_ciks(session, list(run.params["tickers"]))
    return [runner.create_run(SecCompanyJob.name, {"cik": cik}, window) for cik in ciks]
