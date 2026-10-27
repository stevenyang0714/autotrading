"""The real holdings now, or a check of the stored snapshots: `make holdings-snapshot`,
`make holdings-verify` (inside the api container).

    python -m autotrading.jobs.holdings_snapshot [--verify N [--sample M]]

--verify N recomputes the latest N stored holdings snapshots at their own known_at and
system_time, here, and reports any that differ (ADR-041 H13). --sample M adds M random ones.
The output names no position (H12).
"""

import argparse
import logging
import sys

from sqlalchemy import func, select

from autotrading.db.models import HoldingSnapshot
from autotrading.jobs import actors
from autotrading.repositories.holdings import recompute


def verify(count: int, sample: int) -> int:
    with actors.sessions()() as session:
        rows = list(
            session.scalars(
                select(HoldingSnapshot).order_by(HoldingSnapshot.recorded_at.desc()).limit(count)
            )
        )
        if sample:
            rows += session.scalars(
                select(HoldingSnapshot).order_by(func.random()).limit(sample)
            ).all()
        unique = list({row.id: row for row in rows}.values())
        differ = [
            f"{row.known_at.isoformat()} {row.trigger}"
            for row in unique
            if recompute(session, row) != row.holdings
        ]
    print(f"recomputed {len(unique)} holdings snapshots: {len(unique) - len(differ)} identical")
    for line in differ:
        print(f"  differs: {line}")
    return 1 if differ else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", type=int, metavar="N")
    parser.add_argument("--sample", type=int, default=0, metavar="M")
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify, args.sample)
    actors.start_holdings_snapshot(manual=True)
    print("Queued a holdings snapshot now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
