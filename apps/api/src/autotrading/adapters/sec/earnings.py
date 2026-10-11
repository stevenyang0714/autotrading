"""Job `sec.earnings_release`: one company's earnings 8-Ks (Item 2.02), read for numeric
guidance (M1.5, ADR-026 E3, P1-3).

fetch: per filing, `{accession}-index-headers.html`, then its EX-99 exhibits (the release and,
for some issuers, a CFO commentary); the 8-K body only refers to them. All under
www.sec.gov/Archives/edgar/data/, which the SEC client already allows.
store: the revenue, EPS and margin outlooks their text states (domain/guidance.py), at the
filing's stored acceptance time. Only the sentence is stored; the raw documents stay in the
private payload store. A filing read without guidance stores nothing: the run's parameters
record which filings were read at which extractor version (adapters/sec/refresh.py), so the
API can tell "guidance not extracted" from "not read yet".
"""

from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import SOURCE_TIMEZONE
from autotrading.adapters.sec.eight_k import (
    INDEX_SUFFIX,
    FilingNotStoredError,
    folder_url,
    read_documents,
)
from autotrading.adapters.sec.parsing import normalize_cik
from autotrading.adapters.sec.tickers import NAMESPACE, SOURCE_ID
from autotrading.db.models import Filing, FilingGuidanceStatement, Source
from autotrading.domain.buyback_announcements import document_text
from autotrading.domain.guidance import GUIDANCE_VERSION, guidance
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.repositories.audit import set_actor
from autotrading.repositories.identifiers import current_identifier

ACTOR = f"ingest:{SOURCE_ID}"


def exhibits(index: bytes) -> list[tuple[str, str]]:
    """(type, file name) of a filing's EX-99 exhibits."""
    return [(kind, name) for kind, name in read_documents(index) if kind.startswith("EX-99")]


@register_job
class SecEarningsReleaseJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "sec.earnings_release"

    def client(self) -> SecClient:
        return SecClient.from_settings()

    @property
    def cik(self) -> str:
        return normalize_cik(self.params["cik"])

    @property
    def accessions(self) -> list[str]:
        return [f["accession"] for f in self.params["filings"]]

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        payloads: list[FetchedPayload] = []
        with self.client() as client:
            for accession in self.accessions:
                folder = folder_url(self.cik, accession)
                index = client.get(f"{folder}/{accession}{INDEX_SUFFIX}", ctx.acquire)
                payloads.append(index)
                payloads += [
                    client.get(f"{folder}/{name}", ctx.acquire)
                    for _, name in exhibits(index.content)
                ]
        return payloads

    def store(self, ctx: StoreContext) -> StoreResult:
        session = ctx.session
        cik_identifier = current_identifier(session, "cik", NAMESPACE, self.cik)
        entity_id = cik_identifier.entity_id if cik_identifier else None
        if entity_id is None:
            raise FilingNotStoredError(f"no entity for CIK {self.cik}; run sec.tickers first")
        filings = {
            f.accession_number: f
            for f in session.scalars(
                select(Filing).where(
                    Filing.entity_id == entity_id, Filing.accession_number.in_(self.accessions)
                )
            )
        }
        documents: dict[str, tuple[str, str]] = {}  # document URL -> (accession, type)
        for payload in ctx.payloads:
            if payload.source_url.endswith(INDEX_SUFFIX):
                accession = payload.source_url.rsplit("/", 1)[1].removesuffix(INDEX_SUFFIX)
                folder = folder_url(self.cik, accession)
                for kind, name in exhibits(payload.content):
                    documents[f"{folder}/{name}"] = (accession, kind)
        source = session.get_one(Source, SOURCE_ID)
        rows, notes = [], []
        for payload in ctx.payloads:
            if payload.source_url not in documents:
                continue
            accession, document_type = documents[payload.source_url]
            filing = filings.get(accession)
            if filing is None:
                raise FilingNotStoredError(f"filing {accession} of CIK {self.cik} is not stored")
            found = guidance(document_text(payload.content, rows=True))
            for g in found:
                rows.append(
                    {
                        "entity_id": entity_id,
                        "accession_number": accession,
                        "document": payload.source_url.rsplit("/", 1)[1],
                        "document_type": document_type,
                        "metric": g.metric,
                        "low": g.low,
                        "high": g.high,
                        "unit": g.unit,
                        "period_text": g.period,
                        "adjusted": g.adjusted,
                        "sentence": g.sentence,
                        "rule": g.rule,
                        "extractor_version": GUIDANCE_VERSION,
                        "source_id": source.id,
                        "source_tier": source.tier,
                        "source_url": payload.source_url,
                        "published_at": filing.published_at,
                        "published_at_precision": filing.published_at_precision,
                        "ingested_at": payload.fetched_at,
                        "effective_from": filing.published_at,
                        "effective_to": None,
                        "as_of": filing.published_at,
                        "license_status": source.license_status,
                        "confidence": 1,
                        "source_timezone": SOURCE_TIMEZONE,
                        "ingestion_run_id": ctx.run_id,
                        "raw_payload_sha256": payload.sha256,
                    }
                )
            notes += [f"{accession} {document_type}: {g.metric} {g.low}-{g.high}" for g in found]
        inserted = 0
        if rows:
            set_actor(session, ACTOR)
            result = session.execute(
                insert(FilingGuidanceStatement)
                .values(rows)
                .on_conflict_do_nothing(constraint="uq_filing_guidance_statements_source_value")
                .returning(FilingGuidanceStatement.id)
            )
            inserted = len(result.all())
        return StoreResult(
            inserted=inserted,
            unchanged=len(rows) - inserted,
            conflicted=0,
            notes=tuple(notes),
        )
