"""FinMind (M3.7b, ADR-040), inside the api container:

    python -m autotrading.jobs.finmind_refresh             # `make finmind-refresh`: flows now
    python -m autotrading.jobs.finmind_refresh --backfill  # `make finmind-backfill`: the history

The history is one run per Taiwan universe code and dataset (66 runs, one request each, about
12.5 s apart under the free tier's cap), 2016-01-01 to 2026-10-20: the sessions before the
first TWSE one. Re-running stores nothing new (TW24: a TWSE row is never overwritten).
"""

import argparse
import sys

from autotrading.jobs import actors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args()
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
