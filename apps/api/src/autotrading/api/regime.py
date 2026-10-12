"""Market Regime (M2.1, ADR-029): the stored macro regime and stress state as known at T, with
every input and its vintage, and its history. Nothing is evaluated on request.

- `GET /regime`: the latest assessment at or before T under the active rule version, and the
  history of states (each assessment's T, stress, quadrant and dimension states).
- `GET /regime/rules`: the released regime rule sets.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import RegimeAssessment
from autotrading.db.models import RegimeRuleSet as RegimeRuleSetRow
from autotrading.domain.regime import Regime
from autotrading.repositories.regime import active_regime_version, load_regime_rules

router = APIRouter(tags=["regime"])

NOT_A_FORECAST = (
    "Deterministic rules on data known at the date: a description of conditions, not a "
    "forecast. Thresholds are defaults, unvalidated (OD-7)."
)


class StoredRegime(BaseModel):
    id: UUID
    known_at: datetime
    system_time: datetime
    backfilled: bool
    regime: Regime


class RegimePoint(BaseModel):
    known_at: datetime
    stress: str | None
    quadrant: str | None
    states: dict[str, str]  # dimension -> state
    flags_on: int
    flags_available: int
    backfilled: bool


class RegimeOut(BaseModel):
    known_at: datetime
    rule_version: str
    current: StoredRegime | None
    history: list[RegimePoint]
    detail: str = NOT_A_FORECAST


class RegimeRuleSetOut(BaseModel):
    rule_version: str
    status: Literal["active", "retired"]
    released: date
    content: dict[str, Any]
    content_sha256: str


@router.get("/regime/rules")
def regime_rules(session: SessionDep) -> list[RegimeRuleSetOut]:
    file = load_regime_rules()
    status = {r.rule_version: r.status for r in file.rule_sets}
    return [
        RegimeRuleSetOut(
            rule_version=row.rule_version,
            status=status.get(row.rule_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in session.scalars(
            select(RegimeRuleSetRow).order_by(RegimeRuleSetRow.loaded_at.desc())
        )
    ]


@router.get("/regime")
def regime(session: SessionDep, known_at: KnownAt = None) -> RegimeOut:
    at = known_at_or_now(session, known_at)
    version = active_regime_version()
    rows = session.scalars(
        select(RegimeAssessment)
        .where(RegimeAssessment.rule_version == version, RegimeAssessment.known_at <= at)
        .order_by(RegimeAssessment.known_at)
    ).all()
    history = [
        RegimePoint(
            known_at=r.known_at,
            stress=r.stress,
            quadrant=r.quadrant,
            states={d["dimension"]: d["state"] for d in r.assessment["dimensions"]},
            flags_on=r.flags_on,
            flags_available=r.flags_available,
            backfilled=r.backfilled,
        )
        for r in rows
    ]
    last = rows[-1] if rows else None
    return RegimeOut(
        known_at=at,
        rule_version=version,
        current=StoredRegime(
            id=last.id,
            known_at=last.known_at,
            system_time=last.system_time,
            backfilled=last.backfilled,
            regime=Regime.model_validate(last.assessment),
        )
        if last
        else None,
        history=history,
    )
