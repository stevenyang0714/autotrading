"""S3 ETF rotation (M2.4, ADR-032): the stored rotation as known at T, with every ETF's trend,
gate and inputs, and the history of its targets. Nothing is evaluated on request.

- `GET /rotation`: the latest assessment at or before T under the active rule version, and every
  target set since (month starts and defensive switches).
- `GET /rotation/rules`: the released rotation rule sets.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import RotationAssessment
from autotrading.db.models import RotationRuleSet as RotationRuleSetRow
from autotrading.domain.rotation import Rotation
from autotrading.repositories.rotation import active_rotation_version, load_rotation_rules

router = APIRouter(tags=["rotation"])

RESEARCH_ONLY = (
    "Research only (paper): each ETF against its own trend, gated by the market's stress state. "
    "No order, and no journal entry for ETFs yet. Thresholds are defaults, unvalidated (OD-7)."
)


class StoredRotation(BaseModel):
    id: UUID
    known_at: datetime
    system_time: datetime
    backfilled: bool
    rotation: Rotation


class RotationPoint(BaseModel):
    """A target as it was set: at a month start or a defensive switch."""

    id: UUID
    known_at: datetime
    reason: str
    stress: str | None
    target: dict[str, Decimal]
    cash_pct: Decimal
    backfilled: bool


class RotationOut(BaseModel):
    known_at: datetime
    rule_version: str
    current: StoredRotation | None
    history: list[RotationPoint]
    detail: str = RESEARCH_ONLY


class RotationRuleSetOut(BaseModel):
    rule_version: str
    status: Literal["active", "retired"]
    released: date
    content: dict[str, Any]
    content_sha256: str


@router.get("/rotation/rules")
def rotation_rules(session: SessionDep) -> list[RotationRuleSetOut]:
    file = load_rotation_rules()
    status = {r.rule_version: r.status for r in file.rule_sets}
    return [
        RotationRuleSetOut(
            rule_version=row.rule_version,
            status=status.get(row.rule_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in session.scalars(
            select(RotationRuleSetRow).order_by(RotationRuleSetRow.loaded_at.desc())
        )
    ]


def stored(row: RotationAssessment) -> StoredRotation:
    return StoredRotation(
        id=row.id,
        known_at=row.known_at,
        system_time=row.system_time,
        backfilled=row.backfilled,
        rotation=Rotation.model_validate(row.assessment),
    )


def latest_rotation(session: SessionDep, at: datetime) -> RotationAssessment | None:
    return session.scalars(
        select(RotationAssessment)
        .where(
            RotationAssessment.rule_version == active_rotation_version(),
            RotationAssessment.known_at <= at,
        )
        .order_by(RotationAssessment.known_at.desc())
        .limit(1)
    ).first()


@router.get("/rotation")
def rotation(session: SessionDep, known_at: KnownAt = None) -> RotationOut:
    at = known_at_or_now(session, known_at)
    version = active_rotation_version()
    rows = session.scalars(
        select(RotationAssessment)
        .where(
            RotationAssessment.rule_version == version,
            RotationAssessment.known_at <= at,
            RotationAssessment.rebalance,
        )
        .order_by(RotationAssessment.known_at)
    ).all()
    history = [
        RotationPoint(
            id=r.id,
            known_at=r.known_at,
            reason=r.reason,
            stress=r.stress,
            target={symbol: Decimal(weight) for symbol, weight in (r.target or {}).items()},
            cash_pct=Decimal(r.assessment["cash_pct"]),
            backfilled=r.backfilled,
        )
        for r in rows
    ]
    last = latest_rotation(session, at)
    return RotationOut(
        known_at=at,
        rule_version=version,
        current=stored(last) if last else None,
        history=history,
    )
