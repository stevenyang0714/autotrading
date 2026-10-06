"""Job `sec.filing_xbrl`: one company's filings, read from their own XBRL instances (M1.1,
ADR-021).

fetch: the `{primary document}_htm.xml` instance SEC extracts from each inline XBRL filing.
store: share counts a filing tags per class only, added up (instance.class_sums) and stored as
facts of that filing at its stored acceptance time. All filings of the run are written in one
batch in publication order, so a comparative repeated by a later filing never comes first.
Class sets a filing does not confirm are not added; they are recorded as run notes. Then each
filing is reconciled with what we store (adapters/sec/reconcile.py); the issuer-wide split
check goes with the newest 10-K of the run. A failing reconciliation is a run note too.

adapters/sec/refresh.py chooses the filings: one run per company and refresh, each filing read
once per methodology version.
"""

from datetime import datetime
from typing import ClassVar, cast

from sqlalchemy import select

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import Stamp, fact_in
from autotrading.adapters.sec.instance import (
    class_sums,
    confirmed_class_sets,
    instance_url,
    parse_instance,
)
from autotrading.adapters.sec.parsing import normalize_cik
from autotrading.adapters.sec.reconcile import reconcile_filing
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

METHODOLOGY_VERSION = "0.1.1"
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
        rows, notes, parsed = [], [], []
        instances = {p.source_url: parse_instance(p.content) for p in ctx.payloads}
        # Class sets any filing of the run confirms (the latest 10-K for Alphabet's Class C).
        confirmed = set().union(*(confirmed_class_sets(i) for i in instances.values()))
        for payload in ctx.payloads:
            accession = documents[payload.source_url]
            filing = filings.get(accession)
            if filing is None:
                raise FilingNotStoredError(f"filing {accession} of CIK {self.cik} is not stored")
            instance = instances[payload.source_url]
            sums = class_sums(instance, accession, filing.form, filing.filing_date, confirmed)
            parsed.append((filing, payload, instance, sums.values))
            published: dict[str, tuple[datetime, TimePrecision]] = {
                accession: (filing.published_at, cast(TimePrecision, filing.published_at_precision))
            }
            rows += [
                fact_in(v, entity_id, self.cik, published, payload, stamp) for v in sums.values
            ]
            notes += [f"{accession}: {finding}" for finding in sums.findings]
        result = FinancialFactRepository(session).insert_many(rows, actor=ACTOR)
        session.flush()
        ten_ks = [f for f, *_ in parsed if f.form == "10-K"] or [f for f, *_ in parsed]
        split_checked = max(ten_ks, key=lambda f: f.filing_date) if ten_ks else None
        for filing, payload, instance, values in parsed:
            reconciliation = reconcile_filing(
                session,
                entity_id=entity_id,
                filing=filing,
                instance=instance,
                sums=values,
                source_url=payload.source_url,
                sha256=payload.sha256,
                run_id=ctx.run_id,
                with_split_check=filing is split_checked,
            )
            if reconciliation is not None and reconciliation.status != "pass":
                notes.append(
                    f"{filing.accession_number}: reconciliation {reconciliation.status} ("
                    f"{reconciliation.mismatched} mismatched, {reconciliation.missing} missing, "
                    f"{reconciliation.extra} extra, {reconciliation.checks_failed} checks failed, "
                    f"{reconciliation.checks_flagged} flagged)"
                )
        return StoreResult(
            inserted=result.inserted,
            unchanged=result.unchanged,
            conflicted=len(result.conflicts),
            notes=tuple(notes),
        )
