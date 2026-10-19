"""domain/progress: parsing the project documents, and the real documents parse."""

import re
from pathlib import Path

from autotrading.domain.progress import (
    parse_current,
    parse_log,
    parse_milestones,
    parse_open_decisions,
    parse_phases,
)
from autotrading.settings import Settings

STATUS = """# STATUS
## Current
- Phase: 0 — Foundation
- Sub-milestone: M0.6 FRED / ALFRED adapter — LOCAL ACCEPTANCE PASSED; PR + CI pending
- Next: M0.7 market data

## Log
| Date | Sub-milestone | Result | Notes |
|---|---|---|---|
| 2026-10-06 | M0.6 | Local acceptance passed. Migration 0006. | gaps |
| 2026-10-05 | M0.5 | Done. PR merged. | - |
"""

MILESTONES = """## M0.5 SEC EDGAR adapter
**Acceptance**
- [x] Facts ingested.
- [x] Restatement test.

## M0.6 FRED / ALFRED adapter
**Acceptance**
- [x] Revision test.
- [x] Macro page toggle.

## M0.7 Market data adapter
**Acceptance**
- [ ] Data unavailable without a key.

## M0.10 Phase 0 exit report
Write the report.
"""

PROPOSED = """# Phase 1 — Fundamentals

**Status:** Proposed — awaiting Steven's approval

## M1.1 Financial data
**Acceptance**
- [ ] Facts reconcile to filings.
"""


def test_current_section_and_log() -> None:
    current = parse_current(STATUS)
    assert current.get("Next") == "M0.7 market data"
    log = parse_log(STATUS)
    assert [(e.date, e.milestone, e.result) for e in log] == [
        ("2026-10-06", "M0.6", "Local acceptance passed."),
        ("2026-10-05", "M0.5", "Done."),
    ]


def test_milestone_status_from_checkboxes_and_the_current_sub_milestone() -> None:
    milestones = parse_milestones(MILESTONES, parse_current(STATUS))
    assert [(m.id, m.done, m.total, m.status) for m in milestones] == [
        ("M0.5", 2, 2, "done"),
        ("M0.6", 2, 2, "in_progress"),  # all boxes ticked, but its PR is still pending
        ("M0.7", 0, 1, "not_started"),
        ("M0.10", 0, 0, "not_started"),
    ]


def test_milestones_of_a_proposed_phase_file_are_proposed() -> None:
    (milestone,) = parse_milestones(PROPOSED, parse_current(STATUS))
    assert (milestone.id, milestone.total, milestone.status) == ("M1.1", 1, "proposed")


def test_real_documents_parse() -> None:
    docs = Settings(_env_file=None).resolved_docs_dir()  # type: ignore[call-arg]
    current = parse_current((docs / "STATUS.md").read_text(encoding="utf-8"))
    milestones = parse_milestones(
        (docs / "milestones" / "M0_foundation.md").read_text(encoding="utf-8"), current
    )
    assert [m.id for m in milestones][:3] == ["M0.1", "M0.2", "M0.3"]
    assert next(m for m in milestones if m.id == "M0.1").status == "done"
    phases = parse_phases((docs / "milestones" / "ROADMAP.md").read_text(encoding="utf-8"))
    assert [p.number for p in phases] == [1, 2, 3, 4, 5, 6]
    decisions = parse_open_decisions(
        (docs / "decisions" / "DECISIONS.md").read_text(encoding="utf-8")
    )
    assert [d.id for d in decisions][:2] == ["OD-3", "OD-4"]  # OD-1, OD-2 decided (ADR-035)
    assert re.match(r"\d", current.get("Phase") or "")  # the current phase number


def test_paths_exist() -> None:
    docs = Settings(_env_file=None).resolved_docs_dir()  # type: ignore[call-arg]
    assert Path(docs / "STATUS.md").is_file()
