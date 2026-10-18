"""S4 momentum (M3.0, ADR-036 D7): the stored daily assessment as known at T, with every
company's conditions and inputs, and the history of its targets. Nothing is evaluated on
request.

- `GET /momentum`: the latest assessment at or before T under the active momentum rule version,
  and every target set since (month starts). The rule sets are at `GET /momentum/rules`.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import MomentumAssessment as MomentumAssessmentRow
from autotrading.domain.momentum import MomentumAssessment
from autotrading.repositories.backtest import active_momentum_version, stored_momentum_rules

router = APIRouter(tags=["momentum"])

RESEARCH_ONLY = (
    "Research only (paper): each company's 12-1 momentum, alone and against SPY, against its own "
    "history; no ranking across companies. No order. Thresholds are defaults, unvalidated (OD-7)."
)


class StoredMomentum(BaseModel):
    id: UUID
    known_at: datetime
    system_time: datetime
    backfilled: bool
    momentum: MomentumAssessment


class MomentumPoint(BaseModel):
    """A target as it was set, at the first assessment of a month."""

    id: UUID
    known_at: datetime
    reason: str
    target: dict[str, Decimal]
    cash_pct: Decimal
    backfilled: bool


class MomentumOut(BaseModel):
    known_at: datetime
    rule_version: str
    current: StoredMomentum | None
    history: list[MomentumPoint]
    detail: str = RESEARCH_ONLY


def ordered(target: dict[str, str], order: list[str]) -> dict[str, Decimal]:
    """A stored target in universe order (JSONB keeps its own key order)."""
    keys = sorted(target, key=lambda s: (order.index(s) if s in order else len(order), s))
    return {s: Decimal(target[s]) for s in keys}


def stored(row: MomentumAssessmentRow) -> StoredMomentum:
    return StoredMomentum(
        id=row.id,
        known_at=row.known_at,
        system_time=row.system_time,
        backfilled=row.backfilled,
        momentum=MomentumAssessment.model_validate(row.assessment),
    )


def latest_momentum(session: SessionDep, at: datetime) -> MomentumAssessmentRow | None:
    return session.scalars(
        select(MomentumAssessmentRow)
        .where(
            MomentumAssessmentRow.rule_version == active_momentum_version(),
            MomentumAssessmentRow.known_at <= at,
        )
        .order_by(MomentumAssessmentRow.known_at.desc())
        .limit(1)
    ).first()


@router.get("/momentum")
def momentum(session: SessionDep, known_at: KnownAt = None) -> MomentumOut:
    at = known_at_or_now(session, known_at)
    version = active_momentum_version()
    rules = stored_momentum_rules(session, version)
    order = list(rules.universe) if rules else []
    rows = session.scalars(
        select(MomentumAssessmentRow)
        .where(
            MomentumAssessmentRow.rule_version == version,
            MomentumAssessmentRow.known_at <= at,
            MomentumAssessmentRow.rebalance,
        )
        .order_by(MomentumAssessmentRow.known_at)
    ).all()
    history = [
        MomentumPoint(
            id=r.id,
            known_at=r.known_at,
            reason=r.reason,
            target=ordered(r.target or {}, order),
            cash_pct=Decimal(r.assessment["cash_pct"]),
            backfilled=r.backfilled,
        )
        for r in rows
    ]
    current = latest_momentum(session, at)
    return MomentumOut(
        known_at=at,
        rule_version=version,
        current=stored(current) if current is not None else None,
        history=history,
    )
