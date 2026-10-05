"""Manual FRED / ALFRED refresh: `make fred-refresh` (inside the api container).

Queues the same runs as the daily schedule; the worker executes them. Progress shows on the
Data Health page (http://127.0.0.1:3000/system/data-health).
"""

import logging
import sys

from autotrading.jobs import actors


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_ids = actors.start_fred_refresh(manual=True)
    if not run_ids:
        print("fred is not enabled in config/sources.yaml (or no series is enabled).")
        return 1
    print(f"Queued {len(run_ids)} fred.series runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
