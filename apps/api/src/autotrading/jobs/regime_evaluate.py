"""The macro regime now, or backfilled: `make regime-evaluate`, `make regime-backfill` (inside
the api container). Queues the same work as the daily schedule; the worker executes it.

    python -m autotrading.jobs.regime_evaluate [--backfill | --verify N]

--verify N recomputes the latest N stored assessments with their own known_at, system_time and
rule version, here, and reports any that differ (Phase 2 exit: regime reproducible).
"""

import argparse
import logging
import sys

from sqlalchemy import select

from autotrading.db.models import RegimeAssessment
from autotrading.jobs import actors
from autotrading.repositories.regime import regime_at, stored_regime_rules


def verify(count: int) -> int:
    with actors.sessions()() as session:
        rows = session.scalars(
            select(RegimeAssessment).order_by(RegimeAssessment.recorded_at.desc()).limit(count)
        ).all()
        differ = []
        for row in rows:
            rules = stored_regime_rules(session, row.rule_version)
            assert rules is not None
            again = regime_at(session, rules, row.known_at, row.system_time)
            if again.model_dump(mode="json") != row.assessment:
                differ.append(f"{row.known_at.isoformat()} {row.rule_version}")
    print(f"recomputed {len(rows)} regime assessments: {len(rows) - len(differ)} identical")
    for line in differ:
        print(f"  differs: {line}")
    return 1 if differ else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--verify", type=int, metavar="N")
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify)
    if args.backfill:
        months = actors.start_regime_backfill()
        print(f"Queued regime assessments for {months} month ends since 2016.")
        return 0
    actors.start_regime_evaluation(manual=True)
    print("Queued a regime assessment now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
