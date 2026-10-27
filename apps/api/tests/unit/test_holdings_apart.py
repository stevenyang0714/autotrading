"""Real holdings stay apart from research and the paper portfolio (M3.10, ADR-041 H4, H12): only
the holdings modules (and the audit viewer's labels) read the ledger or its snapshots, so no
rule, alert, push, radar or paper book can see them."""

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "autotrading"
LEDGER = re.compile(
    r"HoldingEntry|HoldingSnapshot|holding_entries|holding_snapshots"
    r"|(?:repositories|domain|api)\.holdings|holdings\.(?:record_snapshot|valuation_at|recompute)"
)
ALLOWED = {
    "api/holdings.py",
    "api/audit.py",  # labels on the audit log page
    "db/models.py",
    "domain/holdings.py",
    "repositories/holdings.py",
    "jobs/actors.py",  # the daily snapshot actor
    "jobs/scheduler.py",
    "jobs/holdings_snapshot.py",
    "ingestion/schedule.py",
    "main.py",
}


def test_only_the_holdings_modules_name_the_ledger() -> None:
    readers = {
        str(path.relative_to(SOURCE))
        for path in SOURCE.rglob("*.py")
        if LEDGER.search(path.read_text(encoding="utf-8"))
    }
    assert readers <= ALLOWED, f"outside the holdings modules: {sorted(readers - ALLOWED)}"
