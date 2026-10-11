"""Signals (M1.6, ADR-027 J1): stored with each qualifying buyback state assignment, listed per
point in time. A signal is paper_only: nothing here or anywhere places an order (ADR-008).

`GET /signals` lists each company's current signal and, for one ticker, its history. Writing is
in repositories/signals.py, called by `record_assignment`.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
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
from autotrading.db.models import BuybackStateAssignment, SignalRecord
from autotrading.domain.registries import SIGNAL_FAMILIES, STRATEGIES

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
    state: str  # of the assignment it came from
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
    rule_version: str  # the active buyback rule version
    current: list[SignalOut]  # each company whose latest assignment at T qualifies
    history: list[SignalOut]  # one ticker's signals, newest first (with ?ticker=)


def signal_out(row: SignalRecord, state: str) -> SignalOut:
    return SignalOut(
        id=row.id,
        ticker=row.ticker,
        family_id=row.family_id,
        family=FAMILY_NAMES[row.family_id],
        strategy_id=row.strategy_id,
        strategy=STRATEGY_NAMES.get(row.strategy_id or ""),
        rule_version=row.rule_version,
        state=state,
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
    return select(SignalRecord, BuybackStateAssignment.state).join(
        BuybackStateAssignment,
        and_(
            BuybackStateAssignment.instrument_id == SignalRecord.instrument_id,
            BuybackStateAssignment.known_at == SignalRecord.generated_at,
            BuybackStateAssignment.rule_version == SignalRecord.rule_version,
        ),
    )


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


def signal_history(session: Session, ticker: str, at: datetime, limit: int) -> list[SignalOut]:
    rows = session.execute(
        _with_state()
        .where(SignalRecord.ticker == ticker.upper(), SignalRecord.generated_at <= at)
        .order_by(SignalRecord.generated_at.desc(), SignalRecord.rule_version.desc())
        .limit(limit)
    ).all()
    return [signal_out(row, state) for row, state in rows]


@router.get("/signals")
def signals(
    session: SessionDep,
    known_at: KnownAt = None,
    ticker: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> SignalsOut:
    at = known_at_or_now(session, known_at)
    rule_version = active_rule_version()
    return SignalsOut(
        known_at=at,
        rule_version=rule_version,
        current=current_signals(session, at, rule_version),
        history=signal_history(session, ticker, at, limit) if ticker else [],
    )
