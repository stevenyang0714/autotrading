"""Backtests now: `make backtest-run` (inside the api container). Queues the same work as the
monthly schedule, without its once-a-month check; the worker executes it.

    python -m autotrading.jobs.backtest_evaluate [--verify N]

--verify N recomputes the latest N stored runs with their own known_at, system_time and rule
versions, here, and reports any that differ (ADR-033).
"""

import argparse
import logging
import sys

from sqlalchemy import select

from autotrading.db.models import BacktestRun
from autotrading.jobs import actors
from autotrading.repositories.backtest import recompute, same


def verify(count: int) -> int:
    with actors.sessions()() as session:
        rows = session.scalars(
            select(BacktestRun).order_by(BacktestRun.recorded_at.desc()).limit(count)
        ).all()
        differ = []
        for row in rows:
            again = recompute(session, row)
            if again is None or not same(row, again):
                differ.append(f"{row.strategy_id} {row.known_at.isoformat()} {row.rule_version}")
    print(f"recomputed {len(rows)} backtest runs: {len(rows) - len(differ)} identical")
    for line in differ:
        print(f"  differs: {line}")
    return 1 if differ else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", type=int, metavar="N")
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify)
    actors.start_backtests(manual=True)
    print("Queued the backtests of S1, S3 and S4 now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
