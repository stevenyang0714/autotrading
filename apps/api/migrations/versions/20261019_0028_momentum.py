"""S4's daily assessment (M3.0, ADR-036 D7): momentum_assessments, append-only.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-19

- momentum_assessments: strategy S4 at a time T as held at system_time, under one momentum rule
  version: every company's reading, the target in force and why (set at the first assessment of
  each New York month, carried otherwise). One row per T and rule version; `previous_id` is the
  assessment whose target it carried. Not audited (like the rotation assessments).
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "momentum_assessments",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("rebalance", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("previous_id", sa.Uuid(), nullable=True),
        sa.Column("assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("reason IN ('month_start', 'carried', 'unavailable')", name="reason"),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint(
            "(reason = 'unavailable') = (target IS NULL)", name="target_when_available"
        ),
        sa.CheckConstraint("rebalance = (reason = 'month_start')", name="rebalance_at_month_start"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["momentum_rule_sets.rule_version"],
            name="fk_momentum_assessments_rule_version_momentum_rule_sets",
        ),
        sa.ForeignKeyConstraint(
            ["previous_id"],
            ["momentum_assessments.id"],
            name="fk_momentum_assessments_previous_id_momentum_assessments",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_momentum_assessments"),
        sa.UniqueConstraint(
            "known_at", "rule_version", name="uq_momentum_assessments_known_at_rule"
        ),
    )
    op.execute(
        "CREATE TRIGGER momentum_assessments_append_only BEFORE UPDATE OR DELETE "
        "ON momentum_assessments FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER momentum_assessments_no_truncate BEFORE TRUNCATE "
        "ON momentum_assessments FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def downgrade() -> None:
    op.drop_table("momentum_assessments")
