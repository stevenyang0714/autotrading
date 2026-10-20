"""The S3 ETF rotation now, or backfilled: `make rotation-evaluate`, `make rotation-backfill`
(inside the api container). Queues the same work as the daily schedule; the worker executes it.

    python -m autotrading.jobs.rotation_evaluate [--backfill | --verify N]

--verify N recomputes the latest N stored assessments of every rule version with their own
known_at, system_time, rule version and previous target, here, and reports any that differ
(ADR-032; ADR-036: a retired version's rows stay identical).
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
        versions = session.scalars(select(RotationAssessment.rule_version).distinct()).all()
        rows = [
            row
            for version in sorted(versions)
            for row in session.scalars(
                select(RotationAssessment)
                .where(RotationAssessment.rule_version == version)
                .order_by(RotationAssessment.recorded_at.desc())
                .limit(count)
            )
        ]
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
        points = actors.start_rotation_backfill()
        print(f"Queued the rotation at {points} session closes and month ends since 2017.")
        return 0
    actors.start_rotation_evaluation(manual=True)
    print("Queued a rotation assessment now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
