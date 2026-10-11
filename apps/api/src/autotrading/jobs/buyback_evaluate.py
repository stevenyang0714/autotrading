"""Buyback states now, or backfilled: `make buyback-evaluate`, `make buyback-backfill` (inside
the api container). Queues the same work as the daily schedule; the worker executes it.

    python -m autotrading.jobs.buyback_evaluate [--backfill | --verify N]

--verify N recomputes the latest N stored assignments with their own known_at, system_time,
rule version and extractor version, here, and reports any that differ (acceptance 1).
"""

import argparse
import logging
import sys

from sqlalchemy import select

from autotrading.api.buyback_states import evaluate, stored_rule_set
from autotrading.db.models import BuybackStateAssignment, Instrument
from autotrading.jobs import actors


def verify(count: int) -> int:
    with actors.sessions()() as session:
        rows = session.scalars(
            select(BuybackStateAssignment)
            .order_by(BuybackStateAssignment.recorded_at.desc())
            .limit(count)
        ).all()
        differ = []
        for row in rows:
            again = evaluate(
                session,
                session.get_one(Instrument, row.instrument_id),
                row.known_at,
                row.system_time,
                stored_rule_set(session, row.rule_version),
                row.extractor_version,
            )
            if again.model_dump(mode="json") != row.assessment:
                differ.append(f"{row.ticker} {row.known_at.isoformat()} {row.rule_version}")
    print(f"recomputed {len(rows)} assignments: {len(rows) - len(differ)} identical")
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
        months = actors.start_buyback_backfill()
        print(f"Queued buyback state backfills for {months} month ends since 2021.")
        return 0
    actors.start_buyback_evaluation(manual=True)
    print("Queued a buyback state evaluation of every universe equity now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
