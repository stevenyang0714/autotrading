"""Insert-only access to signals (M1.6, ADR-027 J1): the signal of each qualifying buyback state
assignment, in the caller's transaction. One row per company, family, time and rule version.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.db.models import BuybackStateAssignment, SignalRecord
from autotrading.domain.signals import QUALIFYING_STATES, SignalIn, buyback_signal


def record_signal(
    session: Session, instrument_id: UUID, ticker: str, signal: SignalIn
) -> UUID | None:
    """Insert one signal; None when this company, family, time and rule version has one."""
    return session.execute(
        insert(SignalRecord)
        .values(
            instrument_id=instrument_id,
            ticker=ticker,
            family_id=signal.family_id,
            strategy_id=signal.strategy_id,
            rule_version=signal.rule_version,
            score=signal.score,
            direction=signal.direction,
            generated_at=signal.generated_at,
            valid_from=signal.valid_from,
            system_time=signal.system_time,
            observation_ids=signal.observation_ids,
            source_quality=signal.source_quality,
            evidence_independence=signal.evidence_independence,
            execution_eligibility=signal.execution_eligibility,
            backfilled=signal.backfilled,
        )
        .on_conflict_do_nothing(constraint="uq_signals_instrument_family_time_rule")
        .returning(SignalRecord.id)
    ).scalar()


def assignment_signal(session: Session, row: BuybackStateAssignment) -> UUID | None:
    """Store the signal of one stored assignment, if its state qualifies (J1)."""
    signal = buyback_signal(
        str(row.id),
        row.state,
        row.score,
        row.assessment,
        row.rule_version,
        row.known_at,
        row.system_time,
    )
    return None if signal is None else record_signal(session, row.instrument_id, row.ticker, signal)


def backfill_signals(session: Session) -> int:
    """The signals of every qualifying assignment stored without one; returns how many."""
    stored = select(SignalRecord.id).where(
        SignalRecord.instrument_id == BuybackStateAssignment.instrument_id,
        SignalRecord.generated_at == BuybackStateAssignment.known_at,
        SignalRecord.rule_version == BuybackStateAssignment.rule_version,
    )
    rows = session.scalars(
        select(BuybackStateAssignment)
        .where(BuybackStateAssignment.state.in_(QUALIFYING_STATES), ~stored.exists())
        .order_by(BuybackStateAssignment.known_at)
    ).all()
    return sum(assignment_signal(session, row) is not None for row in rows)
