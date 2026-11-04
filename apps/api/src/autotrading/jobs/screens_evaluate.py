"""The Taiwan screens now, backfilled or verified: `make screens-evaluate`, `make screens-backfill`,
`make screens-verify` (inside the api container; M3.11, ADR-042). Queues the same work as the
schedule; the worker executes it.

    python -m autotrading.jobs.screens_evaluate [--backfill [--since YYYY-MM-DD] | --verify N]

--backfill judges every stored session not judged yet, from the first with 60 sessions before
it, in order (the history check, SC13). --verify N recomputes the latest N judged runs with
their own known_at, system_time, rule version and carried watch lists, here, and reports any
that differ.
"""

import argparse
import logging
import sys
from datetime import date

from sqlalchemy import select

from autotrading.db.models import ScreenRun
from autotrading.jobs import actors
from autotrading.repositories.screens import recompute, same


def verify(count: int) -> int:
    with actors.sessions()() as session:
        rows = session.scalars(
            select(ScreenRun)
            .where(ScreenRun.status == "judged")
            .order_by(ScreenRun.session.desc(), ScreenRun.recorded_at.desc())
            .limit(count)
        ).all()
        differ = [
            f"{row.session} {row.rule_version}"
            for row in rows
            if not same(row, recompute(session, row))
        ]
    print(f"recomputed {len(rows)} Taiwan screen runs: {len(rows) - len(differ)} identical")
    for line in differ:
        print(f"  differs: {line}")
    return 1 if differ else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--since", type=date.fromisoformat)
    parser.add_argument("--verify", type=int, metavar="N")
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify)
    if args.backfill:
        actors.start_screens_backfill(args.since)
        print("Queued the Taiwan screens at every stored session not judged yet.")
        return 0
    actors.start_screens_evaluation(manual=True)
    print("Queued the Taiwan screens now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
