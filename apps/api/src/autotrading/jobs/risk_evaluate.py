"""The paper portfolio now, or a check of the stored risk checks: `make portfolio-snapshot`,
`make risk-verify` (inside the api container).

    python -m autotrading.jobs.risk_evaluate [--verify N [--sample M]]

--verify N recomputes the latest N stored risk checks (journal, on-demand and standard) with
their own known_at, system_time, rule version and trade, here, and reports any that differ
(Phase 2 exit: risk veto deterministic). --sample M adds M random stored checks.
"""

import argparse
import logging
import sys

from sqlalchemy import func, select

from autotrading.db.models import RiskCheck
from autotrading.jobs import actors
from autotrading.repositories.risk import recompute


def verify(count: int, sample: int) -> int:
    with actors.sessions()() as session:
        rows = list(
            session.scalars(select(RiskCheck).order_by(RiskCheck.recorded_at.desc()).limit(count))
        )
        if sample:
            rows += session.scalars(select(RiskCheck).order_by(func.random()).limit(sample)).all()
        unique = list({row.id: row for row in rows}.values())
        differ = []
        for row in unique:
            again = recompute(session, row)
            if again is None or again.model_dump(mode="json") != row.risk_check:
                differ.append(f"{row.ticker} {row.known_at.isoformat()} {row.trigger}")
    print(f"recomputed {len(unique)} risk checks: {len(unique) - len(differ)} identical")
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
    actors.start_portfolio_snapshot(manual=True)
    print("Queued a paper portfolio snapshot now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
