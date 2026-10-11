"""SEC refresh orchestration (M0.5, M1.1, M1.4a): which runs to create, without touching the
broker.

A refresh is one `sec.tickers` run followed, once it succeeds, by one `sec.company` run per
universe equity and per linked predecessor issuer (ADR-014). All runs share one refresh window
(ingestion/schedule.py); the schedule runs daily at 10:00 SGT.

Each `sec.company` run is followed by:
- a `sec.filing_xbrl` run (ADR-021) for filings not read yet at the current methodology
  version: the latest 10-K and 10-Q (reconciliation), and every inline XBRL 10-K/10-Q since
  mid-2019 that left a share count unstored (class sums). A filing another issuer co-filed and
  holds the XBRL of (ExxonMobil Holdings' 10-Q also listed under Exxon Mobil Corp) is not this
  issuer's to read. When class sums are due, the latest 10-K joins the run so its balance
  sheet can confirm the share classes;
- a `sec.eight_k` run (M1.4a, ADR-025) for 8-Ks since 2021 with item 2.02, 7.01 or 8.01 not
  read yet at the current extractor version: at most EIGHT_K_PER_RUN, oldest first, so the
  first backfill spreads over a few refreshes;
- a `sec.earnings_release` run (M1.5, ADR-026) for earnings 8-Ks (Item 2.02) since 2021 not
  read yet for guidance at the current guidance version, the same way.
"""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from autotrading.adapters.sec.company import SecCompanyJob
from autotrading.adapters.sec.earnings import SecEarningsReleaseJob
from autotrading.adapters.sec.eight_k import SecEightKJob
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
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION
from autotrading.domain.guidance import GUIDANCE_VERSION
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
    others = co_filed(session, [f for f in filings if f is not None])
    chosen = {
        f.accession_number: f
        for f in [*latest, *missing_shares]
        if f is not None and f.accession_number not in read and f.accession_number not in others
    }
    if missing_shares and latest[0] is not None and latest[0].accession_number not in others:
        chosen.setdefault(latest[0].accession_number, latest[0])  # confirms share classes
    return sorted(chosen.values(), key=lambda f: (f.filing_date, f.accession_number))


def co_filed(session: Session, filings: list[Filing]) -> set[str]:
    """Accessions whose XBRL facts another issuer holds and this one does not."""
    if not filings:
        return set()
    entity_id = filings[0].entity_id
    accessions = [f.accession_number for f in filings]
    holders = session.execute(
        select(FinancialFact.accession_id, FinancialFact.entity_id)
        .where(FinancialFact.accession_id.in_(accessions))
        .distinct()
    ).all()
    mine = {a for a, e in holders if a and e == entity_id}
    return {a for a, e in holders if a and e != entity_id} - mine


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


# ---------- 8-Ks for buyback announcements (M1.4a, ADR-025 B1, B2) ----------

EIGHT_K_SINCE = date(2021, 1, 1)
EIGHT_K_FORMS = ("8-K", "8-K/A")
# Results (earnings releases), Regulation FD and other events: where buybacks are announced.
EIGHT_K_ITEMS = frozenset({"2.02", "7.01", "8.01"})
EIGHT_K_PER_RUN = 50


@dataclass(frozen=True)
class FilingReader:
    """A job that reads a company's 8-Ks once per extractor version: which forms and items,
    and the version its runs record (`params["extractor"]`)."""

    job: str
    version: str
    forms: tuple[str, ...]
    items: frozenset[str]


EIGHT_K_READER = FilingReader(SecEightKJob.name, EXTRACTOR_VERSION, EIGHT_K_FORMS, EIGHT_K_ITEMS)
# Earnings releases (M1.5, ADR-026 E1): 8-Ks with Item 2.02, not amendments.
EARNINGS_READER = FilingReader(
    SecEarningsReleaseJob.name, GUIDANCE_VERSION, ("8-K",), frozenset({"2.02"})
)


def reader_accessions(session: Session, reader: FilingReader, cik: str) -> set[str]:
    """Filings of `cik` already read by a successful run of `reader` at its version."""
    runs = session.scalars(
        select(IngestionRun.params).where(
            IngestionRun.job == reader.job,
            IngestionRun.status == "succeeded",
            IngestionRun.params["cik"].astext == cik,
            IngestionRun.params["extractor"].astext == reader.version,
        )
    )
    return {f["accession"] for params in runs for f in params["filings"]}


def candidates(session: Session, reader: FilingReader, cik: str) -> list[Filing]:
    """Filings of `cik` for `reader` not read yet, oldest first (see the module docstring)."""
    read = reader_accessions(session, reader, cik)
    filings = session.scalars(
        select(Filing)
        .where(
            Filing.cik == cik,
            Filing.form.in_(reader.forms),
            Filing.filing_date >= EIGHT_K_SINCE,
        )
        .order_by(Filing.filing_date, Filing.accession_number)
    )
    return [
        f
        for f in filings
        if f.accession_number not in read and reader.items & set((f.items or "").split(","))
    ]


def reader_run(
    runner: IngestionRunner,
    reader: FilingReader,
    cik: str,
    only: set[str] | frozenset[str] | None = None,
) -> UUID | None:
    """One run of `reader` for up to EIGHT_K_PER_RUN unread filings of `cik` (None if there
    are none); `only` limits the accessions (recorded replays)."""
    with runner.sessions() as session:
        found = [
            f
            for f in candidates(session, reader, cik)
            if only is None or f.accession_number in only
        ][:EIGHT_K_PER_RUN]
        if not found:
            return None
        params = {
            "cik": cik,
            "filings": [{"accession": f.accession_number} for f in found],
            "extractor": reader.version,
        }
        window = Window(start=found[0].published_at, end=found[-1].published_at)
    return runner.create_run(reader.job, params, window)


def _company_cik(runner: IngestionRunner, company_run_id: UUID) -> str:
    with runner.sessions() as session:
        return str(session.get_one(IngestionRun, company_run_id).params["cik"])


def read_eight_k_accessions(session: Session, cik: str) -> set[str]:
    """8-Ks of `cik` already read by a successful `sec.eight_k` run at this extractor version."""
    return reader_accessions(session, EIGHT_K_READER, cik)


def eight_k_candidates(session: Session, cik: str) -> list[Filing]:
    return candidates(session, EIGHT_K_READER, cik)


def create_eight_k_run(
    runner: IngestionRunner, company_run_id: UUID, only: set[str] | frozenset[str] | None = None
) -> UUID | None:
    """One `sec.eight_k` run for the company run's CIK (see reader_run)."""
    return reader_run(runner, EIGHT_K_READER, _company_cik(runner, company_run_id), only)


def eight_k_run(
    runner: IngestionRunner, cik: str, only: set[str] | frozenset[str] | None = None
) -> UUID | None:
    return reader_run(runner, EIGHT_K_READER, cik, only)


def create_earnings_run(
    runner: IngestionRunner, company_run_id: UUID, only: set[str] | frozenset[str] | None = None
) -> UUID | None:
    """One `sec.earnings_release` run for the company run's CIK (M1.5, see reader_run)."""
    return reader_run(runner, EARNINGS_READER, _company_cik(runner, company_run_id), only)


def read_earnings_accessions(session: Session, cik: str) -> set[str]:
    """Earnings 8-Ks of `cik` read for guidance at the current extractor version."""
    return reader_accessions(session, EARNINGS_READER, cik)
