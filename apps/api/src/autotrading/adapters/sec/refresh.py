"""SEC refresh orchestration (M0.5, M1.1): which runs to create, without touching the broker.

A refresh is one `sec.tickers` run followed, once it succeeds, by one `sec.company` run per
universe equity and per linked predecessor issuer (ADR-014). All runs share one refresh window
(ingestion/schedule.py); the schedule runs daily at 10:00 SGT.

Each `sec.company` run is followed by `sec.filing_xbrl` runs (ADR-021) for filings not read yet
at the current methodology version: the latest 10-K and 10-Q (reconciliation), and every
inline XBRL 10-K/10-Q since mid-2019 that left a share count unstored (class sums).
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from autotrading.adapters.sec.company import SecCompanyJob
from autotrading.adapters.sec.filing_xbrl import METHODOLOGY_VERSION, SecFilingXbrlJob
from autotrading.adapters.sec.tickers import NAMESPACE, SOURCE_ID, Predecessor, SecTickersJob
from autotrading.db.models import (
    EntityRelationship,
    Filing,
    FinancialFact,
    Identifier,
    IngestionRun,
    Instrument,
    Source,
)
from autotrading.ingestion.job import Window
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window


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


# Inline XBRL became mandatory for large accelerated filers for periods ending after this date.
INLINE_XBRL_SINCE = date(2019, 6, 15)
READ_FORMS = ("10-K", "10-Q")
SHARE_METRICS = ("shares_outstanding", "shares_outstanding_cover")


def read_accessions(session: Session, cik: str) -> set[str]:
    """Filings of `cik` already read by a successful `sec.filing_xbrl` run at this version."""
    runs = session.scalars(
        select(IngestionRun.params).where(
            IngestionRun.job == SecFilingXbrlJob.name,
            IngestionRun.status == "succeeded",
            IngestionRun.params["cik"].astext == cik,
            IngestionRun.params["methodology"].astext == METHODOLOGY_VERSION,
        )
    )
    return {f["accession"] for params in runs for f in params["filings"]}


def filing_xbrl_candidates(session: Session, cik: str) -> list[Filing]:
    """Filings of `cik` whose instance to read, oldest first (see the module docstring)."""
    filings = [
        f
        for f in session.scalars(
            select(Filing)
            .where(
                Filing.cik == cik,
                Filing.form.in_(READ_FORMS),
                Filing.is_inline_xbrl.is_(True),
                Filing.primary_document.is_not(None),
                Filing.filing_date >= INLINE_XBRL_SINCE,
            )
            .order_by(Filing.filing_date.desc(), Filing.accession_number.desc())
        )
    ]
    latest = [next((f for f in filings if f.form == form), None) for form in READ_FORMS]
    missing_shares = [
        f
        for f in filings
        if not all(
            session.scalar(
                select(
                    exists().where(
                        FinancialFact.entity_id == f.entity_id,
                        FinancialFact.accession_id == f.accession_number,
                        FinancialFact.metric_id == metric,
                    )
                )
            )
            for metric in SHARE_METRICS
        )
    ]
    read = read_accessions(session, cik)
    chosen = {
        f.accession_number: f
        for f in [*latest, *missing_shares]
        if f is not None and f.accession_number not in read
    }
    return sorted(chosen.values(), key=lambda f: (f.filing_date, f.accession_number))


def create_filing_xbrl_run(
    runner: IngestionRunner, company_run_id: UUID, only: set[str] | frozenset[str] | None = None
) -> UUID | None:
    """One `sec.filing_xbrl` run for the candidate filings of the company run's CIK (None if
    there are none); `only` limits the accessions (recorded replays)."""
    with runner.sessions() as session:
        run = session.get_one(IngestionRun, company_run_id)
        cik = str(run.params["cik"])
        candidates = [
            f
            for f in filing_xbrl_candidates(session, cik)
            if only is None or f.accession_number in only
        ]
        if not candidates:
            return None
        params = {
            "cik": cik,
            "filings": [
                {"accession": f.accession_number, "document": f.primary_document}
                for f in candidates
            ],
            "methodology": METHODOLOGY_VERSION,
        }
        window = Window(start=candidates[0].published_at, end=candidates[-1].published_at)
    return runner.create_run(SecFilingXbrlJob.name, params, window)
