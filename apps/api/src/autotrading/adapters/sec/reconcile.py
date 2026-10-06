"""Reconcile a filing's own XBRL instance with what we store (M1.1, ADR-021).

Called by `sec.filing_xbrl` after a filing's class sums are written, inside the same
transaction. Reads the stored facts as known at the filing's acceptance time and now, the
splits of the issuer's instrument, and writes one filing_reconciliations row with its items
(domain/reconciliation.py decides each status).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.sec.concepts import METRIC_MAPPINGS
from autotrading.adapters.sec.instance import (
    IDENTITY_CONCEPTS,
    InstanceFact,
    as_companyfacts,
)
from autotrading.adapters.sec.parsing import XbrlValue, select_values
from autotrading.db.models import (
    Filing,
    FilingReconciliation,
    FinancialFact,
    Instrument,
    ReconciliationItem,
    SplitEvent,
)
from autotrading.domain.reconciliation import (
    METHODOLOGY_VERSION,
    QUARTER_CHECK_METRICS,
    Key,
    Result,
    Stored,
    fact_items,
    identity_items,
    quarter_items,
    split_items,
)
from autotrading.domain.splits import ADJUSTED_METRICS, ReportedVersion, Split, unexplained_splits
from autotrading.repositories.facts import as_of_query

MAPPED_METRICS = tuple(m.metric_id for m in METRIC_MAPPINGS)
FAR_FUTURE = datetime(9999, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class _View:
    """A stored fact for the domain functions (domain/derived.ValueFact)."""

    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date


def _known(session: Session, entity_id: UUID, at: datetime) -> list[FinancialFact]:
    return list(
        session.scalars(
            as_of_query(FinancialFact, known_at=at).where(
                FinancialFact.entity_id == entity_id, FinancialFact.metric_id.in_(MAPPED_METRICS)
            )
        )
    )


def _by_key(facts: Iterable[FinancialFact]) -> dict[Key, Stored]:
    return {
        (f.metric_id, f.period_start, f.period_end): Stored(f.value, f.accession_id) for f in facts
    }


def filing_values(
    facts: list[InstanceFact], sums: list[XbrlValue], filing: Filing
) -> dict[Key, Decimal]:
    shaped = as_companyfacts(facts, filing.accession_number, filing.form, filing.filing_date)
    values: dict[Key, Decimal] = {}
    for value in [*select_values(shaped), *sums]:
        values.setdefault((value.metric_id, value.period_start, value.period_end), value.value)
    return values


def reconcile_filing(
    session: Session,
    *,
    entity_id: UUID,
    filing: Filing,
    instance: list[InstanceFact],
    sums: list[XbrlValue],
    source_url: str,
    sha256: str,
    run_id: UUID,
    with_split_check: bool,
) -> FilingReconciliation | None:
    """None when this filing was already reconciled at this methodology version."""
    exists = session.scalar(
        select(FilingReconciliation.id).where(
            FilingReconciliation.entity_id == entity_id,
            FilingReconciliation.accession_number == filing.accession_number,
            FilingReconciliation.methodology_version == METHODOLOGY_VERSION,
        )
    )
    if exists is not None:
        return None
    reported = filing_values(instance, sums, filing)
    then = _known(session, entity_id, filing.published_at)
    now = _known(session, entity_id, FAR_FUTURE)
    under = {
        (f.metric_id, f.period_start, f.period_end)
        for f in session.scalars(
            select(FinancialFact).where(
                FinancialFact.entity_id == entity_id,
                FinancialFact.accession_id == filing.accession_number,
            )
        )
    }
    instants = {
        (f.concept, f.context.end): f.value
        for f in instance
        if not f.context.dims and f.context.start is None and f.concept in IDENTITY_CONCEPTS
    }
    three_months = {
        key: value
        for key, value in reported.items()
        if key[0] in QUARTER_CHECK_METRICS
        and key[1] is not None
        and timedelta(days=80) <= key[2] - key[1] <= timedelta(days=100)
    }
    views = [_View(f.metric_id, f.value, f.period_start, f.period_end) for f in then]
    items = [
        *fact_items(reported, _by_key(then), _by_key(now), under),
        *identity_items(instants),
        *quarter_items(views, three_months),
    ]
    if with_split_check:
        items += split_items(_split_findings(session, entity_id))
    result = Result(items)
    row = FilingReconciliation(
        entity_id=entity_id,
        accession_number=filing.accession_number,
        form=filing.form,
        filing_published_at=filing.published_at,
        source_url=source_url,
        raw_payload_sha256=sha256,
        methodology_version=METHODOLOGY_VERSION,
        checked=sum(1 for i in items if i.check == "fact" and i.status != "extra"),
        matched=result.count("match", "fact"),
        mismatched=result.count("mismatch", "fact"),
        missing=result.count("missing", "fact"),
        extra=result.count("extra", "fact"),
        restated_later=result.count("restated_later", "fact"),
        checks_failed=result.count("fail"),
        checks_flagged=result.count("flag"),
        status=result.status,
        ingestion_run_id=run_id,
    )
    session.add(row)
    session.flush()
    session.add_all(
        ReconciliationItem(
            reconciliation_id=row.id,
            check_kind=item.check,
            status=item.status,
            metric_id=item.metric_id,
            period_start=item.period_start,
            period_end=item.period_end,
            filing_value=item.filing_value,
            stored_value=item.stored_value,
            current_value=item.current_value,
            stored_accession=item.stored_accession,
            detail=item.detail,
        )
        for item in items
    )
    session.flush()
    return row


def _split_findings(session: Session, entity_id: UUID) -> list[str]:
    instrument = session.scalar(select(Instrument.id).where(Instrument.entity_id == entity_id))
    splits = (
        [
            Split(s.ex_date, s.old_rate, s.new_rate)
            for s in session.scalars(
                select(SplitEvent).where(SplitEvent.instrument_id == instrument)
            )
        ]
        if instrument
        else []
    )
    versions = [
        ReportedVersion(
            f.metric_id, f.period_start, f.period_end, f.value, f.published_at, f.accession_id
        )
        for f in session.scalars(
            select(FinancialFact).where(
                FinancialFact.entity_id == entity_id,
                FinancialFact.metric_id.in_(ADJUSTED_METRICS),
                FinancialFact.superseded_at.is_(None),
            )
        )
    ]
    return unexplained_splits(versions, splits)
