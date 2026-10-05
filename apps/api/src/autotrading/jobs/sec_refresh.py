"""Manual SEC EDGAR refresh: `make sec-refresh` (inside the api container).

Queues the same runs as the daily schedule; the worker executes them. Progress shows on the
Data Health page (http://127.0.0.1:3000/system/data-health).
"""

import logging
import sys

from autotrading.jobs import actors


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_id = actors.start_sec_refresh(manual=True)
    if run_id is None:
        print("sec_edgar is not enabled in config/sources.yaml; run `make migrate` after enabling.")
        return 1
    print(f"Queued sec.tickers run {run_id}; company runs follow once it succeeds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
