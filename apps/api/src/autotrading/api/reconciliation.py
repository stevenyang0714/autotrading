"""Filing reconciliation API (M1.1, ADR-021): each issuer's latest 10-K and 10-Q checked
against their own XBRL instances, and the items of one filing. Read-only.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.db.models import (
    Entity,
    EntityRelationship,
    Filing,
    FilingReconciliation,
    Identifier,
    Instrument,
    ReconciliationItem,
)
from autotrading.domain.reconciliation import METHODOLOGY_VERSION, Check, Status

router = APIRouter(tags=["reconciliation"])

FORMS = ("10-K", "10-Q")


class ReconciliationOut(BaseModel):
    ticker: str | None
    company: str
    accession: str
    form: str
    filing_published_at: datetime
    filing_url: str | None  # EDGAR index page
    instance_url: str  # the filing's own XBRL instance
    status: Literal["pass", "warn", "fail"]
    checked: int
    matched: int
    mismatched: int
    missing: int
    extra: int
    restated_later: int
    checks_failed: int
    checks_flagged: int
    methodology_version: str
    recorded_at: datetime


class ReconciliationList(BaseModel):
    methodology_version: str
    filings: list[ReconciliationOut]  # latest 10-K and 10-Q per issuer, by ticker


class ItemOut(BaseModel):
    check: Check
    status: Status
    metric_id: str | None
    period_start: date | None
    period_end: date | None
    filing_value: Decimal | None
    stored_value: Decimal | None
    current_value: Decimal | None
    stored_accession: str | None
    detail: str | None


class ReconciliationDetail(BaseModel):
    filing: ReconciliationOut
    items: list[ItemOut]


def _ticker(session: Session, entity_id: UUID) -> str | None:
    """The open SEC ticker of the entity's instrument, else its successor's (ADR-014)."""
    for candidate in (
        entity_id,
        session.scalar(
            select(EntityRelationship.successor_entity_id).where(
                EntityRelationship.predecessor_entity_id == entity_id
            )
        ),
    ):
        if candidate is None:
            continue
        ticker = session.scalar(
            select(Identifier.id_value)
            .join(Instrument, Instrument.id == Identifier.instrument_id)
            .where(
                Instrument.entity_id == candidate,
                Identifier.id_type == "ticker",
                Identifier.id_namespace == "sec",
                Identifier.valid_to.is_(None),
            )
        )
        if ticker is not None:
            return ticker
    return None


def _out(session: Session, row: FilingReconciliation) -> ReconciliationOut:
    filing_url = session.scalar(
        select(Filing.source_url).where(
            Filing.entity_id == row.entity_id, Filing.accession_number == row.accession_number
        )
    )
    return ReconciliationOut(
        ticker=_ticker(session, row.entity_id),
        company=session.get_one(Entity, row.entity_id).name,
        accession=row.accession_number,
        form=row.form,
        filing_published_at=row.filing_published_at,
        filing_url=filing_url,
        instance_url=row.source_url,
        status=cast(Literal["pass", "warn", "fail"], row.status),
        checked=row.checked,
        matched=row.matched,
        mismatched=row.mismatched,
        missing=row.missing,
        extra=row.extra,
        restated_later=row.restated_later,
        checks_failed=row.checks_failed,
        checks_flagged=row.checks_flagged,
        methodology_version=row.methodology_version,
        recorded_at=row.recorded_at,
    )


@router.get("/reconciliation")
def reconciliations(
    session: SessionDep,
    status: Annotated[Literal["pass", "warn", "fail"] | None, Query()] = None,
    form: Annotated[Literal["10-K", "10-Q"] | None, Query()] = None,
) -> ReconciliationList:
    latest = (
        select(FilingReconciliation)
        .where(
            FilingReconciliation.methodology_version == METHODOLOGY_VERSION,
            FilingReconciliation.form.in_([form] if form else FORMS),
        )
        .ext(distinct_on(FilingReconciliation.entity_id, FilingReconciliation.form))
        .order_by(
            FilingReconciliation.entity_id,
            FilingReconciliation.form,
            FilingReconciliation.filing_published_at.desc(),
        )
    )
    rows = [_out(session, r) for r in session.scalars(latest)]
    if status:
        rows = [r for r in rows if r.status == status]
    rows.sort(key=lambda r: (r.ticker or "~", r.company, r.form))
    return ReconciliationList(methodology_version=METHODOLOGY_VERSION, filings=rows)


@router.get("/reconciliation/{accession}")
def reconciliation(accession: str, session: SessionDep) -> ReconciliationDetail:
    row = session.scalars(
        select(FilingReconciliation)
        .where(
            FilingReconciliation.accession_number == accession,
            FilingReconciliation.methodology_version == METHODOLOGY_VERSION,
        )
        .order_by(FilingReconciliation.recorded_at.desc())
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no reconciliation for {accession!r}")
    order = {"mismatch": 0, "missing": 1, "extra": 2, "fail": 3, "flag": 4, "restated_later": 5}
    items = sorted(
        session.scalars(
            select(ReconciliationItem).where(ReconciliationItem.reconciliation_id == row.id)
        ),
        key=lambda i: (
            order.get(i.status, 9),
            i.check_kind,
            i.metric_id or "",
            i.period_end or date.min,
        ),
    )
    return ReconciliationDetail(
        filing=_out(session, row),
        items=[
            ItemOut(
                check=cast(Check, i.check_kind),
                status=cast(Status, i.status),
                metric_id=i.metric_id,
                period_start=i.period_start,
                period_end=i.period_end,
                filing_value=i.filing_value,
                stored_value=i.stored_value,
                current_value=i.current_value,
                stored_accession=i.stored_accession,
                detail=i.detail,
            )
            for i in items
        ],
    )
