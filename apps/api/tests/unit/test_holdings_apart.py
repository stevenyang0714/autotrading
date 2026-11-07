"""Real holdings stay apart from research and the paper portfolio (M3.10, ADR-041 H4, H12): only
the holdings modules (and the audit viewer's labels) read the ledger, its snapshots or the
investment policy (M3.12, ADR-043 IP1), so no rule, alert, push, radar or paper book can see
them."""

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "autotrading"
LEDGER = re.compile(
    r"HoldingEntry|HoldingSnapshot|holding_entries|holding_snapshots"
    r"|(?:repositories|domain|api)\.holdings|holdings\.(?:record_snapshot|valuation_at|recompute)"
    r"|InvestmentPolicy|investment_policies|(?:repositories|domain|api)\.investment_policy\b"
)
ALLOWED = {
    "api/holdings.py",
    "api/audit.py",  # labels on the audit log page
    "db/models.py",
    "domain/holdings.py",
    "repositories/holdings.py",
    "api/investment_policy.py",  # the investment policy (M3.12) reads the valuation
    "domain/investment_policy.py",
    "repositories/investment_policy.py",
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
