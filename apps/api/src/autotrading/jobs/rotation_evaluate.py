"""The S3 ETF rotation now, or backfilled: `make rotation-evaluate`, `make rotation-backfill`
(inside the api container). Queues the same work as the daily schedule; the worker executes it.

    python -m autotrading.jobs.rotation_evaluate [--backfill | --verify N]

--verify N recomputes the latest N stored assessments with their own known_at, system_time,
rule version and previous target, here, and reports any that differ (ADR-032).
"""

import argparse
import logging
import sys

from sqlalchemy import select

from autotrading.db.models import RotationAssessment
from autotrading.jobs import actors
from autotrading.repositories.rotation import recompute, same


def verify(count: int) -> int:
    with actors.sessions()() as session:
        rows = session.scalars(
            select(RotationAssessment).order_by(RotationAssessment.recorded_at.desc()).limit(count)
        ).all()
        differ = []
        for row in rows:
            again = recompute(session, row)
            if again is None or not same(row, again):
                differ.append(f"{row.known_at.isoformat()} {row.rule_version}")
    print(f"recomputed {len(rows)} rotation assessments: {len(rows) - len(differ)} identical")
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
        months = actors.start_rotation_backfill()
        print(f"Queued the rotation at {months} month ends since 2017, in order.")
        return 0
    actors.start_rotation_evaluation(manual=True)
    print("Queued a rotation assessment now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
