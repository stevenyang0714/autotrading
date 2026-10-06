"""Job `sec.filing_xbrl`: one company's filings, read from their own XBRL instances (M1.1,
ADR-021).

fetch: the `{primary document}_htm.xml` instance SEC extracts from each inline XBRL filing.
store: share counts a filing tags per class only, added up (instance.class_sums) and stored as
facts of that filing at its stored acceptance time. All filings of the run are written in one
batch in publication order, so a comparative repeated by a later filing never comes first.
Class sets a filing does not confirm are not added; they are recorded as run notes.

adapters/sec/refresh.py chooses the filings: one run per company and refresh, each filing read
once per methodology version.
"""

from datetime import datetime
from typing import ClassVar, cast

from sqlalchemy import select

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import Stamp, fact_in
from autotrading.adapters.sec.instance import class_sums, instance_url, parse_instance
from autotrading.adapters.sec.parsing import normalize_cik
from autotrading.adapters.sec.tickers import NAMESPACE, SOURCE_ID
from autotrading.db.models import Filing, Source
from autotrading.domain.provenance import TimePrecision
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.repositories.facts import FinancialFactRepository
from autotrading.repositories.identifiers import current_identifier

METHODOLOGY_VERSION = "0.1.0"
ACTOR = f"ingest:{SOURCE_ID}"


class FilingNotStoredError(LookupError):
    """The filing is not in `filings` yet: `sec.company` stores it first."""


@register_job
class SecFilingXbrlJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "sec.filing_xbrl"

    def client(self) -> SecClient:
        return SecClient.from_settings()

    @property
    def cik(self) -> str:
        return normalize_cik(self.params["cik"])

    @property
    def documents(self) -> dict[str, str]:
        """Instance URL -> accession, for every filing of the run."""
        return {
            instance_url(self.cik, f["accession"], f["document"]): f["accession"]
            for f in self.params["filings"]
        }

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        with self.client() as client:
            return [client.get(url, ctx.acquire) for url in self.documents]

    def store(self, ctx: StoreContext) -> StoreResult:
        session = ctx.session
        cik_identifier = current_identifier(session, "cik", NAMESPACE, self.cik)
        entity_id = cik_identifier.entity_id if cik_identifier else None
        if entity_id is None:
            raise FilingNotStoredError(f"no entity for CIK {self.cik}; run sec.tickers first")
        documents = self.documents
        filings = {
            f.accession_number: f
            for f in session.scalars(
                select(Filing).where(
                    Filing.entity_id == entity_id,
                    Filing.accession_number.in_(documents.values()),
                )
            )
        }
        stamp = Stamp(session.get_one(Source, SOURCE_ID), ctx.run_id)
        rows, notes = [], []
        for payload in ctx.payloads:
            accession = documents[payload.source_url]
            filing = filings.get(accession)
            if filing is None:
                raise FilingNotStoredError(f"filing {accession} of CIK {self.cik} is not stored")
            sums = class_sums(
                parse_instance(payload.content), accession, filing.form, filing.filing_date
            )
            published: dict[str, tuple[datetime, TimePrecision]] = {
                accession: (filing.published_at, cast(TimePrecision, filing.published_at_precision))
            }
            rows += [
                fact_in(v, entity_id, self.cik, published, payload, stamp) for v in sums.values
            ]
            notes += [f"{accession}: {finding}" for finding in sums.findings]
        result = FinancialFactRepository(session).insert_many(rows, actor=ACTOR)
        return StoreResult(
            inserted=result.inserted,
            unchanged=result.unchanged,
            conflicted=len(result.conflicts),
            notes=tuple(notes),
        )
