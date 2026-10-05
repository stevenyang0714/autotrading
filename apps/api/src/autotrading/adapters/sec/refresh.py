"""SEC refresh orchestration (M0.5): which runs to create, without touching the broker.

A refresh is one `sec.tickers` run followed, once it succeeds, by one `sec.company` run per
universe equity and per linked predecessor issuer (ADR-014). All runs share one refresh window
(ingestion/schedule.py); the schedule runs daily at 10:00 SGT.
"""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from autotrading.adapters.sec.company import SecCompanyJob
from autotrading.adapters.sec.tickers import NAMESPACE, SOURCE_ID, Predecessor, SecTickersJob
from autotrading.db.models import EntityRelationship, Identifier, IngestionRun, Instrument, Source
from autotrading.ingestion.job import Window
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window

REFRESH_HOUR = 10


def universe_equities(config_dir: Path) -> list[str]:
    data = yaml.safe_load((config_dir / "universe.yaml").read_text(encoding="utf-8"))
    return sorted({str(ticker).upper() for ticker in data.get("equities") or []})


def source_enabled(session: Session) -> bool:
    source = session.get(Source, SOURCE_ID)
    return source is not None and source.enabled


def universe_predecessors(config_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """`predecessors:` of universe.yaml, validated, as JSON-ready job params (ADR-014)."""
    data = yaml.safe_load((config_dir / "universe.yaml").read_text(encoding="utf-8"))
    raw: dict[str, list[dict[str, Any]]] = data.get("predecessors") or {}
    return {
        str(ticker).upper(): [
            Predecessor.model_validate(item).model_dump(mode="json") for item in items
        ]
        for ticker, items in sorted(raw.items())
    }


def company_ciks(session: Session, tickers: list[str]) -> list[str]:
    """CIKs behind the universe tickers and their linked predecessors, from the identifiers
    and relationships `sec.tickers` maintains."""
    ticker_id = Identifier.__table__.alias("ticker_id")
    cik_id = Identifier.__table__.alias("cik_id")
    issuers = (
        select(Instrument.entity_id)
        .join(ticker_id, ticker_id.c.instrument_id == Instrument.id)
        .where(
            ticker_id.c.id_type == "ticker",
            ticker_id.c.id_namespace == NAMESPACE,
            ticker_id.c.id_value.in_(tickers),
            ticker_id.c.valid_to.is_(None),
        )
    )
    predecessors = select(EntityRelationship.predecessor_entity_id).where(
        EntityRelationship.successor_entity_id.in_(issuers)
    )
    query = (
        select(cik_id.c.id_value)
        .where(
            cik_id.c.id_type == "cik",
            cik_id.c.id_namespace == NAMESPACE,
            cik_id.c.valid_to.is_(None),
            or_(cik_id.c.entity_id.in_(issuers), cik_id.c.entity_id.in_(predecessors)),
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
        {
            "tickers": universe_equities(config_dir),
            "predecessors": universe_predecessors(config_dir),
        },
        refresh_window(now, manual=manual),
    )


def create_company_runs(runner: IngestionRunner, tickers_run_id: UUID) -> list[UUID]:
    """One `sec.company` run per CIK, in the window of the tickers run that preceded it."""
    with runner.sessions() as session:
        run = session.get_one(IngestionRun, tickers_run_id)
        window = Window(start=run.window_start, end=run.window_end)
        ciks = company_ciks(session, list(run.params["tickers"]))
    return [runner.create_run(SecCompanyJob.name, {"cik": cik}, window) for cik in ciks]
