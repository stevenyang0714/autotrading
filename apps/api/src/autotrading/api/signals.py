"""Signals (M1.6, ADR-027 J1): stored with each qualifying buyback state assignment (S1) and,
since M2.4 (ADR-032), with each new S3 ETF rotation target; listed per point in time. A signal
is paper_only: nothing here or anywhere places an order (ADR-008).

`GET /signals` lists the current signals (each company's latest qualifying assignment, and the
ETFs of the rotation target in force) and, for one ticker, its history. Writing is in
repositories/signals.py, called by `record_assignment` and `record_rotation`.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from autotrading.api.buyback_states import active_rule_version
from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import BuybackStateAssignment, RotationAssessment, SignalRecord
from autotrading.domain.registries import SIGNAL_FAMILIES, STRATEGIES
from autotrading.domain.rotation import STRATEGY as ROTATION_STRATEGY
from autotrading.domain.signals import BUYBACK_STRATEGY
from autotrading.repositories.rotation import active_rotation_version

router = APIRouter(tags=["signals"])

FAMILY_NAMES = {f.id: f.name for f in SIGNAL_FAMILIES}
STRATEGY_NAMES = {s.id: s.name for s in STRATEGIES}


class SignalOut(BaseModel):
    id: UUID
    ticker: str
    family_id: int
    family: str
    strategy_id: str | None
    strategy: str | None
    rule_version: str
    state: str  # S1: the buyback state of its assignment; S3: `rotation_target`
    weight_pct: Decimal | None = None  # S3: the ETF's weight in the target
    stress: str | None = None  # S3: the stress state the target was set under
    score: Decimal | None
    direction: str
    generated_at: datetime
    valid_from: datetime
    system_time: datetime
    observation_ids: list[dict[str, str]]
    source_quality: int
    evidence_independence: int
    execution_eligibility: str
    backfilled: bool


class SignalsOut(BaseModel):
    known_at: datetime
    rule_version: str  # the active buyback rule version (S1)
    rule_versions: dict[str, str]  # strategy -> its active rule version
    current: list[SignalOut]  # S1: each company's latest qualifying assignment; S3: the target
    history: list[SignalOut]  # one ticker's signals, newest first (with ?ticker=)


Strategy = Literal["S1", "S3"]
ROTATION_TARGET = "rotation_target"


def signal_out(
    row: SignalRecord,
    state: str,
    weight: Decimal | None = None,
    stress: str | None = None,
) -> SignalOut:
    return SignalOut(
        id=row.id,
        ticker=row.ticker,
        family_id=row.family_id,
        family=FAMILY_NAMES[row.family_id],
        strategy_id=row.strategy_id,
        strategy=STRATEGY_NAMES.get(row.strategy_id or ""),
        rule_version=row.rule_version,
        state=state,
        weight_pct=weight,
        stress=stress,
        score=row.score,
        direction=row.direction,
        generated_at=row.generated_at,
        valid_from=row.valid_from,
        system_time=row.system_time,
        observation_ids=row.observation_ids,
        source_quality=row.source_quality,
        evidence_independence=row.evidence_independence,
        execution_eligibility=row.execution_eligibility,
        backfilled=row.backfilled,
    )


def _with_state() -> Any:
    """S1 signals with the state of the assignment they came from."""
    return (
        select(SignalRecord, BuybackStateAssignment.state)
        .join(
            BuybackStateAssignment,
            and_(
                BuybackStateAssignment.instrument_id == SignalRecord.instrument_id,
                BuybackStateAssignment.known_at == SignalRecord.generated_at,
                BuybackStateAssignment.rule_version == SignalRecord.rule_version,
            ),
        )
        .where(SignalRecord.strategy_id == BUYBACK_STRATEGY)
    )


def _with_target() -> Any:
    """S3 signals with the rotation assessment that set their target."""
    return (
        select(SignalRecord, RotationAssessment)
        .join(
            RotationAssessment,
            and_(
                RotationAssessment.known_at == SignalRecord.generated_at,
                RotationAssessment.rule_version == SignalRecord.rule_version,
            ),
        )
        .where(SignalRecord.strategy_id == ROTATION_STRATEGY)
    )


def _rotation_out(row: SignalRecord, assessment: RotationAssessment) -> SignalOut:
    weight = (assessment.target or {}).get(row.ticker)
    return signal_out(row, ROTATION_TARGET, Decimal(weight) if weight else None, assessment.stress)


def current_rotation(session: Session, at: datetime, rule_version: str) -> list[SignalOut]:
    """The signals of the rotation target in force at T: those of the latest target set at or
    before it (a month start or a defensive switch), in universe order."""
    latest = (
        select(RotationAssessment.known_at)
        .where(
            RotationAssessment.rule_version == rule_version,
            RotationAssessment.known_at <= at,
            RotationAssessment.rebalance,
        )
        .order_by(RotationAssessment.known_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = session.execute(
        _with_target()
        .where(SignalRecord.rule_version == rule_version, SignalRecord.generated_at == latest)
        .order_by(SignalRecord.ticker, SignalRecord.family_id.desc())
    ).all()
    return [_rotation_out(row, assessment) for row, assessment in rows]


def current_signals(session: Session, at: datetime, rule_version: str) -> list[SignalOut]:
    """Each company's signal from its latest assignment at or before T, if that one qualifies."""
    latest = (
        select(BuybackStateAssignment.id)
        .where(
            BuybackStateAssignment.rule_version == rule_version,
            BuybackStateAssignment.known_at <= at,
        )
        .ext(distinct_on(BuybackStateAssignment.instrument_id))
        .order_by(BuybackStateAssignment.instrument_id, BuybackStateAssignment.known_at.desc())
    )
    rows = session.execute(
        _with_state()
        .where(BuybackStateAssignment.id.in_(latest))
        .order_by(SignalRecord.score.desc().nulls_last(), SignalRecord.ticker)
    ).all()
    return [signal_out(row, state) for row, state in rows]


def signal_history(
    session: Session, ticker: str, at: datetime, limit: int, strategies: set[str]
) -> list[SignalOut]:
    out: list[SignalOut] = []
    if BUYBACK_STRATEGY in strategies:
        rows = session.execute(
            _with_state()
            .where(SignalRecord.ticker == ticker.upper(), SignalRecord.generated_at <= at)
            .order_by(SignalRecord.generated_at.desc(), SignalRecord.rule_version.desc())
            .limit(limit)
        ).all()
        out += [signal_out(row, state) for row, state in rows]
    if ROTATION_STRATEGY in strategies:
        found = session.execute(
            _with_target()
            .where(SignalRecord.ticker == ticker.upper(), SignalRecord.generated_at <= at)
            .order_by(SignalRecord.generated_at.desc(), SignalRecord.family_id.desc())
            .limit(limit)
        ).all()
        out += [_rotation_out(row, assessment) for row, assessment in found]
    out.sort(key=lambda s: s.generated_at, reverse=True)
    return out[:limit]


@router.get("/signals")
def signals(
    session: SessionDep,
    known_at: KnownAt = None,
    ticker: str | None = None,
    strategy: Annotated[list[Strategy] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> SignalsOut:
    at = known_at_or_now(session, known_at)
    rule_version = active_rule_version()
    rotation_version = active_rotation_version()
    chosen: set[str] = set(strategy) if strategy else {BUYBACK_STRATEGY, ROTATION_STRATEGY}
    current: list[SignalOut] = []
    if BUYBACK_STRATEGY in chosen:
        current += current_signals(session, at, rule_version)
    if ROTATION_STRATEGY in chosen:
        current += current_rotation(session, at, rotation_version)
    return SignalsOut(
        known_at=at,
        rule_version=rule_version,
        rule_versions={BUYBACK_STRATEGY: rule_version, ROTATION_STRATEGY: rotation_version},
        current=current,
        history=signal_history(session, ticker, at, limit, chosen) if ticker else [],
    )
