"""FinMind (M3.7b, ADR-040), inside the api container:

    python -m autotrading.jobs.finmind_refresh             # `make finmind-refresh`: flows now
    python -m autotrading.jobs.finmind_refresh --backfill  # `make finmind-backfill`: the history
    python -m autotrading.jobs.finmind_refresh --listed-backfill [--dataset price|dividends]

The history is one run per Taiwan universe code and dataset (66 runs, one request each, about
12.5 s apart under the free tier's cap), 2016-01-01 to 2026-10-20: the sessions before the
first TWSE one. Re-running stores nothing new (TW24: a TWSE row is never overwritten).

`--listed-backfill` (`make finmind-listed-backfill`, M3.11, ADR-042 SC4): every listed company's
prices since 2024 (outside the universe) and ex-dividend results (all), one run per code and
dataset sent 13 s apart; about 1,080 runs per dataset, so about 4 hours each. `--dataset` queues
one of the two (one a day). Runs that succeeded are not queued again.
"""

import argparse
import sys

from autotrading.adapters.finmind.client import DIVIDENDS, PRICE
from autotrading.jobs import actors

DATASETS = {"price": (PRICE,), "dividends": (DIVIDENDS,)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--listed-backfill", action="store_true")
    parser.add_argument("--dataset", choices=sorted(DATASETS))
    args = parser.parse_args()
    if args.listed_backfill:
        count = actors.start_finmind_listed_backfill(
            DATASETS[args.dataset] if args.dataset else None
        )
        print(
            f"Queued {count} FinMind runs of the listed companies "
            f"(about {count * 13 // 60} minutes)."
        )
        return 0
    if args.backfill:
        count = actors.start_finmind_backfill()
        print(f"Queued {count} FinMind history runs (about {count * 13 // 60} minutes).")
        return 0
    run_id = actors.start_finmind_refresh(manual=True)
    print(
        "FinMind refresh skipped: finmind is not enabled."
        if run_id is None
        else f"Queued {run_id}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
