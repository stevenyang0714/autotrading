"""Manual Alpaca refresh (inside the api container):

    make prices-refresh    # one snapshot now (even outside market hours) + recent daily bars
    make prices-backfill   # daily bars since 2016, raw and split-adjusted (run once)

Both also queue the splits and cash dividends since 2016 (M1.1, M2.2).

The worker executes the runs; progress shows on the Data Health page.
"""

import logging
import sys

from autotrading.jobs import actors


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    backfill = "--backfill" in argv
    bars = actors.start_alpaca_daily_bars(manual=True, backfill=backfill)
    snapshot = None if backfill else actors.start_alpaca_snapshots(force=True)
    if bars is None:
        print("alpaca_iex is not enabled in config/sources.yaml or the Alpaca keys are missing.")
        return 1
    print(
        f"Queued alpaca.daily_bars run {bars}"
        + (f" and alpaca.snapshots run {snapshot}" if snapshot else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
