"""Job `sec.company`: one company's filing index and XBRL facts (M0.5).

fetch: submissions (plus older filing pages), XBRL company facts, and the EDGAR headers of new
filings, whose acceptance times come from them (adapters/sec/acceptance.py), rate limited.
store: new filings into `filings`; mapped XBRL values into `financial_facts` in publication
order, each linked to its accession number, filing index page and acceptance time. A value
that differs from the one known at its publication time becomes a new, restated version.
"""

import json
import logging
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import ClassVar, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.adapters.sec.acceptance import (
    HeaderCheck,
    header_acceptance,
    header_url,
    to_check,
)
from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.parsing import (
    FilingRecord,
    XbrlValue,
    filing_index_url,
    load_companyfacts,
    midnight_utc,
    normalize_cik,
    parse_company,
    parse_filings,
    publication_time,
    select_values,
)
from autotrading.adapters.sec.tickers import NAMESPACE, SOURCE_ID
from autotrading.db.models import Filing, Source
from autotrading.domain.facts import FinancialFactIn
from autotrading.domain.provenance import LicenseStatus, Provenance, TimePrecision
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoredPayload,
    StoreResult,
    register_job,
)
from autotrading.repositories.facts import FinancialFactRepository
from autotrading.repositories.identifiers import current_identifier

logger = logging.getLogger(__name__)

DATA_SEC = "https://data.sec.gov"
SOURCE_TIMEZONE = "America/New_York"
FILINGS_BATCH = 5_000
HEADER_SUFFIX = ".hdr.sgml"
ACTOR = f"ingest:{SOURCE_ID}"


def submissions_url(cik: str) -> str:
    return f"{DATA_SEC}/submissions/CIK{cik}.json"


def submissions_page_url(name: str) -> str:
    return f"{DATA_SEC}/submissions/{name}"


def companyfacts_url(cik: str) -> str:
    return f"{DATA_SEC}/api/xbrl/companyfacts/CIK{cik}.json"


class MissingEntityError(LookupError):
    """The CIK has no entity yet: `sec.tickers` creates it and runs first."""


@register_job
class SecCompanyJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "sec.company"

    def client(self) -> SecClient:
        return SecClient.from_settings()

    @property
    def cik(self) -> str:
        return normalize_cik(self.params["cik"])

    # Recorded fixtures (2026-10-05, before SEC's offset bug) set this: their JSON times were
    # checked against EDGAR index pages (ADR-013), so replays need no headers.
    trust_json_acceptance: ClassVar[bool] = False

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        with self.client() as client:
            main = client.get(submissions_url(self.cik), ctx.acquire)
            pages = [
                client.get(submissions_page_url(name), ctx.acquire)
                for name in parse_company(json.loads(main.content)).extra_pages
            ]
            facts = client.get(companyfacts_url(self.cik), ctx.acquire, allow_missing=True)
            headers = []
            if not self.trust_json_acceptance:
                records = [r for p in [main, *pages] for r in _filings_in(p, self.cik)]
                headers = [
                    client.get(
                        header_url(self.cik, r.accession_number), ctx.acquire, allow_missing=True
                    )
                    for r in to_check(records, self._stored_accessions(ctx))
                ]
        return [main, *pages, *([facts] if facts is not None else []), *filter(None, headers)]

    def _stored_accessions(self, ctx: FetchContext) -> set[str]:
        if ctx.sessions is None:
            raise RuntimeError("sec.company needs database access to tell new filings apart")
        with ctx.sessions() as session:
            return set(
                session.scalars(select(Filing.accession_number).where(Filing.cik == self.cik))
            )

    def store(self, ctx: StoreContext) -> StoreResult:
        session = ctx.session
        cik_identifier = current_identifier(session, "cik", NAMESPACE, self.cik)
        if cik_identifier is None or cik_identifier.entity_id is None:
            raise MissingEntityError(f"no entity for CIK {self.cik}; run sec.tickers first")
        entity_id = cik_identifier.entity_id
        source = session.get_one(Source, SOURCE_ID)
        stamp = Stamp(source, ctx.run_id)

        filings: dict[str, tuple[FilingRecord, StoredPayload]] = {}
        facts_payload: StoredPayload | None = None
        header_times: dict[str, datetime] = {}
        for payload in ctx.payloads:
            if payload.source_url == companyfacts_url(self.cik):
                facts_payload = payload
            elif payload.source_url.endswith(HEADER_SUFFIX):
                accession = payload.source_url.rsplit("/", 1)[-1].removesuffix(HEADER_SUFFIX)
                if (accepted := header_acceptance(payload.content)) is not None:
                    header_times[accession] = accepted
            else:
                for record in _filings_in(payload, self.cik):
                    filings.setdefault(record.accession_number, (record, payload))

        known = set(
            session.scalars(select(Filing.accession_number).where(Filing.entity_id == entity_id))
        )
        notes: tuple[str, ...] = ()
        if not self.trust_json_acceptance:
            check = HeaderCheck(header_times)
            for accession, (record, payload) in filings.items():
                if accession not in known:
                    filings[accession] = (check.apply(record), payload)
            if (note := check.note()) is not None:
                logger.warning("SEC CIK %s: %s", self.cik, note)
                notes = (note,)
        new_filings = _store_filings(session, entity_id, filings.values(), known, stamp)
        old_filings = len(filings) - new_filings

        if facts_payload is None:
            return StoreResult(inserted=new_filings, unchanged=old_filings, notes=notes)
        values = select_values(load_companyfacts(facts_payload.content))
        published = _publication_times(session, entity_id, values, filings, known)
        facts = [
            fact_in(value, entity_id, self.cik, published, facts_payload, stamp) for value in values
        ]
        result = FinancialFactRepository(session).insert_many(facts, actor=ACTOR)
        for conflict in result.conflicts:
            logger.warning("SEC CIK %s conflicting value not stored: %s", self.cik, conflict)
        return StoreResult(
            inserted=new_filings + result.inserted,
            unchanged=old_filings + result.unchanged,
            conflicted=len(result.conflicts),
            notes=notes,
        )


def _publication_times(
    session: Session,
    entity_id: UUID,
    values: list[XbrlValue],
    filings: dict[str, tuple[FilingRecord, StoredPayload]],
    known: set[str],
) -> dict[str, tuple[datetime, TimePrecision]]:
    """When each cited filing became public: the stored time for filings stored before this
    run (never re-read from SEC's JSON), this run's checked time for new ones."""
    cited = {value.accession for value in values}
    stored = session.execute(
        select(Filing.accession_number, Filing.published_at, Filing.published_at_precision).where(
            Filing.entity_id == entity_id, Filing.accession_number.in_(cited & known)
        )
    )
    times: dict[str, tuple[datetime, TimePrecision]] = {
        accession: (published_at, cast(TimePrecision, precision))
        for accession, published_at, precision in stored
    }
    for accession in cited - times.keys():
        if accession in filings:
            times[accession] = filings[accession][0].published()
    return times


class Stamp:
    """Provenance fields shared by every row of one run."""

    def __init__(self, source: Source, run_id: UUID) -> None:
        self.source_id = source.id
        self.tier = source.tier
        # The sources table's CHECK constraint limits it to the LicenseStatus values.
        self.license_status = cast(LicenseStatus, source.license_status)
        self.run_id = run_id

    def provenance(
        self,
        *,
        url: str,
        published: tuple[datetime, TimePrecision],
        payload: StoredPayload,
        effective_from: datetime,
        effective_to: datetime | None,
        as_of: datetime,
    ) -> Provenance:
        return Provenance(
            source_id=self.source_id,
            source_tier=self.tier,
            source_url=url,
            published_at=published[0],
            published_at_precision=published[1],
            ingested_at=payload.fetched_at,
            effective_from=effective_from,
            effective_to=effective_to,
            as_of=as_of,
            license_status=self.license_status,
            confidence=1.0,
            source_timezone=SOURCE_TIMEZONE,
            ingestion_run_id=self.run_id,
            raw_payload_sha256=payload.sha256,
        )


def _filings_in(payload: StoredPayload | FetchedPayload, cik: str) -> Iterator[FilingRecord]:
    data = json.loads(payload.content)
    block = data["filings"]["recent"] if "filings" in data else data
    yield from parse_filings(block, cik)


def _store_filings(
    session: Session,
    entity_id: UUID,
    filings: Iterable[tuple[FilingRecord, StoredPayload]],
    known: set[str],
    stamp: Stamp,
) -> int:
    rows = []
    for record, payload in filings:
        if record.accession_number in known:
            continue
        published = record.published()
        provenance = stamp.provenance(
            url=record.index_url,
            published=published,
            payload=payload,
            effective_from=published[0],
            effective_to=None,
            as_of=midnight_utc(record.report_date) if record.report_date else published[0],
        )
        rows.append(
            {
                "entity_id": entity_id,
                "cik": record.cik,
                "accession_number": record.accession_number,
                "form": record.form,
                "filing_date": record.filing_date,
                "accepted_at": record.accepted_at,
                "report_date": record.report_date,
                "primary_document": record.primary_document,
                "primary_doc_description": record.primary_doc_description,
                "items": record.items,
                "is_xbrl": record.is_xbrl,
                "is_inline_xbrl": record.is_inline_xbrl,
                **provenance.model_dump(),
            }
        )
    for start in range(0, len(rows), FILINGS_BATCH):
        session.execute(
            insert(Filing).on_conflict_do_nothing(index_elements=["entity_id", "accession_number"]),
            rows[start : start + FILINGS_BATCH],
        )
    return len(rows)


def fact_in(
    value: XbrlValue,
    entity_id: UUID,
    cik: str,
    published_times: dict[str, tuple[datetime, TimePrecision]],
    payload: StoredPayload,
    stamp: Stamp,
) -> FinancialFactIn:
    # Not in the submissions index: fall back to the filing date from the XBRL data.
    published = published_times.get(value.accession) or publication_time(None, value.filed)
    period_end = midnight_utc(value.period_end)
    return FinancialFactIn(
        entity_id=entity_id,
        metric_id=value.metric_id,
        value=value.value,
        unit=value.unit,
        currency=value.currency,
        fiscal_period=value.fiscal_period,
        period_start=value.period_start,
        period_end=value.period_end,
        filed_at=published[0],
        accession_id=value.accession,
        source_concept=value.concept,
        provenance=stamp.provenance(
            url=filing_index_url(cik, value.accession),
            published=published,
            payload=payload,
            effective_from=(midnight_utc(value.period_start) if value.period_start else period_end),
            effective_to=period_end,
            as_of=period_end,
        ),
    )
