"""S4 momentum now, or backfilled: `make momentum-evaluate`, `make momentum-backfill` (inside the
api container). Queues the same work as the daily schedule; the worker executes it.

    python -m autotrading.jobs.momentum_evaluate [--backfill | --verify N]

--verify N recomputes the latest N stored assessments of every rule version with their own
known_at, system_time, rule version and previous target, here, and reports any that differ
(ADR-036 D7).
"""

import argparse
import logging
import sys

from sqlalchemy import select

from autotrading.db.models import MomentumAssessment
from autotrading.jobs import actors
from autotrading.repositories.momentum import recompute, same


def verify(count: int) -> int:
    with actors.sessions()() as session:
        versions = session.scalars(select(MomentumAssessment.rule_version).distinct()).all()
        rows = [
            row
            for version in sorted(versions)
            for row in session.scalars(
                select(MomentumAssessment)
                .where(MomentumAssessment.rule_version == version)
                .order_by(MomentumAssessment.recorded_at.desc())
                .limit(count)
            )
        ]
        differ = []
        for row in rows:
            again = recompute(session, row)
            if again is None or not same(row, again):
                differ.append(f"{row.known_at.isoformat()} {row.rule_version}")
    print(f"recomputed {len(rows)} momentum assessments: {len(rows) - len(differ)} identical")
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
        points = actors.start_momentum_backfill()
        print(f"Queued S4 momentum at {points} session closes and month ends since 2017.")
        return 0
    actors.start_momentum_evaluation(manual=True)
    print("Queued an S4 momentum assessment now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
