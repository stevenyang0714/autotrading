"""Factor snapshots now, or backfilled: `make factors-evaluate`, `make factors-backfill` (inside
the api container). Queues the same work as the daily schedule; the worker executes it.

    python -m autotrading.jobs.factors_evaluate [--backfill | --verify N [--sample M]]

--verify N recomputes the latest N stored snapshots with their own known_at, system_time, scope
and definition version, here, and reports any that differ (Phase 2 exit: factor definitions
versioned and reproducible). --sample M adds M random stored snapshots and, for every recorded
split since 2016, the snapshots of that instrument in the ten days around its ex-date.
"""

import argparse
import logging
import sys
from datetime import date, timedelta

from sqlalchemy import func, select

from autotrading.db.models import FactorSnapshot, SplitEvent
from autotrading.jobs import actors
from autotrading.repositories.factors import recompute, same


def verify(count: int, sample: int) -> int:
    with actors.sessions()() as session:
        rows = list(
            session.scalars(
                select(FactorSnapshot).order_by(FactorSnapshot.recorded_at.desc()).limit(count)
            )
        )
        if sample:
            rows += session.scalars(
                select(FactorSnapshot).order_by(func.random()).limit(sample)
            ).all()
            for split in session.scalars(
                select(SplitEvent).where(SplitEvent.ex_date >= date(2016, 1, 1))
            ):
                rows += session.scalars(
                    select(FactorSnapshot)
                    .where(
                        FactorSnapshot.instrument_id == split.instrument_id,
                        FactorSnapshot.known_at >= split.published_at - timedelta(days=10),
                        FactorSnapshot.known_at <= split.published_at + timedelta(days=10),
                    )
                    .order_by(FactorSnapshot.known_at)
                ).all()
        unique = list({row.id: row for row in rows}.values())
        differ = [
            f"{row.symbol} {row.known_at.isoformat()} {row.definition_version} {row.scope}"
            for row in unique
            if not same(row, recompute(session, row))
        ]
    print(f"recomputed {len(unique)} factor snapshots: {len(unique) - len(differ)} identical")
    for line in differ:
        print(f"  differs: {line}")
    return 1 if differ else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--verify", type=int, metavar="N")
    parser.add_argument("--sample", type=int, default=0, metavar="M")
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify, args.sample)
    if args.backfill:
        years = actors.start_factor_backfill()
        print(f"Queued factor snapshots for {years} years since 2016 (every session).")
        return 0
    actors.start_factor_evaluation(manual=True)
    print("Queued factor snapshots now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
