"""Job `sec.eight_k`: one company's 8-Ks, read for buyback announcements (M1.4a, ADR-025 B1).

fetch: per filing, `{accession}-index-headers.html` (each document's type and file name; the
folder's index.json lists names only), then the 8-K itself and its EX-99 exhibits (press
releases). All under www.sec.gov/Archives/edgar/data/, which the SEC client already allows.
store: the authorizations, plans and remaining amounts their sentences state
(domain/buyback_announcements.py), at the filing's stored acceptance time. Only the sentence
is stored; the raw documents stay in the private payload store like every fetched response.

adapters/sec/refresh.py chooses the filings: 8-Ks since 2021 with item 2.02, 7.01 or 8.01, each
read once per extractor version.
"""

import re
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import SOURCE_TIMEZONE
from autotrading.adapters.sec.parsing import SEC_ARCHIVES, normalize_cik
from autotrading.adapters.sec.tickers import NAMESPACE, SOURCE_ID
from autotrading.db.models import Filing, FilingBuybackStatement, Source
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION, document_text, statements
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
INDEX_SUFFIX = "-index-headers.html"
READ_TYPES = ("8-K", "8-K/A")
_DOCUMENTS = re.compile(
    r"&lt;TYPE&gt;(?P<type>[^\n&]+?)\s*\n&lt;SEQUENCE&gt;\d+\s*\n&lt;FILENAME&gt;(?P<name>[^\n&]+)"
)


class FilingNotStoredError(LookupError):
    """The filing is not in `filings` yet: `sec.company` stores it first."""


def folder_url(cik: str, accession: str) -> str:
    return f"{SEC_ARCHIVES}/{int(cik)}/{accession.replace('-', '')}"


def read_documents(index: bytes) -> list[tuple[str, str]]:
    """(type, file name) of the 8-K and its EX-99 exhibits, from an index-headers page."""
    found = (
        (m.group("type").strip(), m.group("name").strip())
        for m in _DOCUMENTS.finditer(index.decode("utf-8", errors="replace"))
    )
    return [(kind, name) for kind, name in found if kind in READ_TYPES or kind.startswith("EX-99")]


@register_job
class SecEightKJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "sec.eight_k"

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
                    for _, name in read_documents(index.content)
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
        # Document URL -> (accession, type), from each filing's index page.
        documents: dict[str, tuple[str, str]] = {}
        for payload in ctx.payloads:
            if payload.source_url.endswith(INDEX_SUFFIX):
                accession = payload.source_url.rsplit("/", 1)[1].removesuffix(INDEX_SUFFIX)
                folder = folder_url(self.cik, accession)
                for kind, name in read_documents(payload.content):
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
            found = statements(document_text(payload.content))
            for s in found:
                rows.append(
                    {
                        "entity_id": entity_id,
                        "accession_number": accession,
                        "document": payload.source_url.rsplit("/", 1)[1],
                        "document_type": document_type,
                        "kind": s.kind,
                        "amount": s.amount,
                        "remaining_amount": s.remaining_amount,
                        "stated_date": s.stated_date,
                        "sentence": s.sentence,
                        "rule": s.rule,
                        "extractor_version": EXTRACTOR_VERSION,
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
            notes += [f"{accession} {document_type}: {s.kind} ${s.amount:,.0f}" for s in found]
        inserted = 0
        if rows:
            set_actor(session, ACTOR)
            result = session.execute(
                insert(FilingBuybackStatement)
                .values(rows)
                .on_conflict_do_nothing(constraint="uq_filing_buyback_statements_source_sentence")
                .returning(FilingBuybackStatement.id)
            )
            inserted = len(result.all())
        return StoreResult(
            inserted=inserted,
            unchanged=len(rows) - inserted,
            conflicted=0,
            notes=tuple(notes),
        )
