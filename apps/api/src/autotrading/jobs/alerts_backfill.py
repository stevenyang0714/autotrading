"""Convergence assessments and alerts for the buyback state assignments stored before M1.7:
`make alerts-backfill` (inside the api container). Run once; a second run adds nothing.

    python -m autotrading.jobs.alerts_backfill

Every stored assignment under the alert rules' buyback rule version gets its assessment, in
order of T per company, as the database holds it now (marked backfilled); level changes raise
backfilled alerts. Then the events of the last `event_lookback_days` raise their L0 alerts
(ADR-028 A3). Since M2.4 (ADR-032) it also raises, under the active alert rules, the market-wide
alerts of the stored regime assessments (stress changes) and rotation assessments (new targets),
in order of T, so a new alert rule version keeps their history.
"""

import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autotrading.api.instruments import issuer_chain, universe_equities
from autotrading.db.models import BuybackStateAssignment, ConvergenceAssessment
from autotrading.jobs import actors
from autotrading.repositories import backtest, momentum, regime, rotation
from autotrading.repositories.convergence import (
    buyback_reading,
    record_convergence,
    seed_event_alerts,
    stored_alert_rules,
)


def backfill(session: Session) -> tuple[int, int]:
    """(assessments stored, event alerts seeded)."""
    rules = stored_alert_rules(session)
    if rules is None:
        raise SystemExit("the alert rules are not loaded: run `make migrate` first")
    now = session.execute(select(func.now())).scalar_one()
    assessed = seeded = 0
    for ticker, instrument, entity in universe_equities(session):
        chain = issuer_chain(session, entity.id).order
        done = select(ConvergenceAssessment.id).where(
            ConvergenceAssessment.instrument_id == instrument.id,
            ConvergenceAssessment.rule_version == rules.rule_version,
            ConvergenceAssessment.known_at == BuybackStateAssignment.known_at,
        )
        rows = session.scalars(
            select(BuybackStateAssignment)
            .where(
                BuybackStateAssignment.instrument_id == instrument.id,
                BuybackStateAssignment.rule_version == rules.buyback_rule_version,
                ~done.exists(),
            )
            .order_by(BuybackStateAssignment.known_at)
        ).all()
        for row in rows:
            reading = buyback_reading(
                row.id, row.state, row.known_at, row.rule_version, row.assessment
            )
            stored = record_convergence(
                session, rules, instrument.id, ticker, chain, reading, row.known_at, now, "backfill"
            )
            assessed += stored is not None
        seeded += seed_event_alerts(session, rules, instrument.id, ticker, chain, now)
        session.commit()
    return assessed, seeded


def market_alerts(session: Session) -> tuple[int, int, int]:
    """(stress-change, rotation and S4 alerts) raised under the active alert rules."""
    now = session.execute(select(func.now())).scalar_one()
    regime_rules = regime.stored_regime_rules(session)
    rotation_rules = rotation.stored_rotation_rules(session)
    momentum_rules = backtest.stored_momentum_rules(session)
    stress = regime.raise_alerts(session, regime_rules, now) if regime_rules else 0
    targets = rotation.raise_alerts(session, rotation_rules, now) if rotation_rules else 0
    s4 = momentum.raise_alerts(session, momentum_rules, now) if momentum_rules else 0
    session.commit()
    return stress, targets, s4


def main() -> int:
    with actors.sessions()() as session:
        assessed, seeded = backfill(session)
        stress, targets, s4 = market_alerts(session)
    print(
        f"Stored {assessed} convergence assessments; seeded {seeded} event alerts; raised "
        f"{stress} stress-change, {targets} rotation and {s4} S4 alerts."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
