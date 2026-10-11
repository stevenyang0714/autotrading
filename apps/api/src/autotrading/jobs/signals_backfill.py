"""Signals of the buyback state assignments stored before M1.6: `make signals-backfill` (inside
the api container). Run once; a second run finds nothing to add (ADR-027 J1).

    python -m autotrading.jobs.signals_backfill
"""

import sys

from autotrading.jobs import actors
from autotrading.repositories.signals import backfill_signals


def main() -> int:
    with actors.sessions()() as session:
        added = backfill_signals(session)
        session.commit()
    print(f"Stored {added} signals from qualifying buyback state assignments.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
