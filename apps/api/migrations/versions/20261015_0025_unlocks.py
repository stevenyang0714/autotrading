"""TRADE-READY, L4 and portfolio alerts (M2.3, ADR-031, P2-7).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-15

- buyback_state_assignments: the state TRADE-READY is allowed (buyback rules 0.3.0 reach it when
  the company's standard paper position passes the risk check).
- convergence_assessments and alerts: levels up to L4 Execution Ready (alert rules 0.3.0).
- alerts: kind `portfolio`, the paper portfolio's drawdown crossing its alert threshold; like
  `regime`, it has no company.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KIND_FIELDS = (
    "(kind = 'level_change' AND direction IS NOT NULL AND assessment_id IS NOT NULL"
    " AND instrument_id IS NOT NULL)"
    " OR (kind = 'event' AND direction IS NULL AND level = 0 AND instrument_id IS NOT NULL)"
    " OR (kind = 'regime' AND direction IS NOT NULL AND assessment_id IS NULL"
    " AND instrument_id IS NULL AND ticker IS NULL)"
)
NEW_KIND_FIELDS = (
    "(kind = 'level_change' AND direction IS NOT NULL AND assessment_id IS NOT NULL"
    " AND instrument_id IS NOT NULL)"
    " OR (kind = 'event' AND direction IS NULL AND level = 0 AND instrument_id IS NOT NULL)"
    " OR (kind IN ('regime', 'portfolio') AND direction IS NOT NULL"
    " AND assessment_id IS NULL AND instrument_id IS NULL AND ticker IS NULL)"
)


def _replace(table: str, old: str, new: str, sql: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{old}"), table, type_="check")
    op.create_check_constraint(new, table, sql)


def upgrade() -> None:
    _replace(
        "buyback_state_assignments",
        "state",
        "state",
        "state IN ('none', 'watch', 'active', 'high_conviction', 'trade_ready')",
    )
    _replace(
        "convergence_assessments",
        "level_phase1",
        "level_range",
        "level IS NULL OR level BETWEEN 0 AND 4",
    )
    _replace("alerts", "level_phase1", "level_range", "level BETWEEN 0 AND 4")
    _replace(
        "alerts",
        "previous_level",
        "previous_level",
        "previous_level IS NULL OR previous_level BETWEEN 0 AND 4",
    )
    _replace("alerts", "kind", "kind", "kind IN ('event', 'level_change', 'regime', 'portfolio')")
    _replace("alerts", "kind_fields", "kind_fields", NEW_KIND_FIELDS)


def downgrade() -> None:
    _replace("alerts", "kind_fields", "kind_fields", OLD_KIND_FIELDS)
    _replace("alerts", "kind", "kind", "kind IN ('event', 'level_change', 'regime')")
    _replace(
        "alerts",
        "previous_level",
        "previous_level",
        "previous_level IS NULL OR previous_level BETWEEN 0 AND 3",
    )
    _replace("alerts", "level_range", "level_phase1", "level BETWEEN 0 AND 3")
    _replace(
        "convergence_assessments",
        "level_range",
        "level_phase1",
        "level IS NULL OR level BETWEEN 0 AND 3",
    )
    _replace(
        "buyback_state_assignments",
        "state",
        "state",
        "state IN ('none', 'watch', 'active', 'high_conviction')",
    )
