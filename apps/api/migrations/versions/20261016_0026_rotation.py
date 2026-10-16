"""S3 ETF rotation research (M2.4, ADR-032): rotation_rule_sets and rotation_assessments,
append-only; the strategy joins the signals' key; rotation alerts.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-16

- rotation_rule_sets: one row per released rule_version of config/rotation_rules.yaml, loaded
  by `make migrate` with the sha256 of its content; audited on insert.
- rotation_assessments: the rotation at a time T as held at system_time, under one rule
  version; one row per T and rule version. Not audited (like the regime assessments).
- signals: the unique key adds strategy_id (NULLS NOT DISTINCT), so S3 and later S4 can both
  make family 5 signals on one ETF at one T. Every existing row stays unique under it.
- alerts: kind `rotation`, a new S3 target; like `regime`, it has no company.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND_FIELDS = (
    "(kind = 'level_change' AND direction IS NOT NULL AND assessment_id IS NOT NULL"
    " AND instrument_id IS NOT NULL)"
    " OR (kind = 'event' AND direction IS NULL AND level = 0 AND instrument_id IS NOT NULL)"
    " OR (kind IN ({kinds}) AND direction IS NOT NULL"
    " AND assessment_id IS NULL AND instrument_id IS NULL AND ticker IS NULL)"
)


def _append_only(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
        f"ON {table} FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE "
        f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def _replace(table: str, old: str, new: str, sql: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{old}"), table, type_="check")
    op.create_check_constraint(new, table, sql)


def upgrade() -> None:
    op.create_table(
        "rotation_rule_sets",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("released", sa.Date(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(r"rule_version ~ '^\d+\.\d+\.\d+$'", name="rule_version_format"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        sa.PrimaryKeyConstraint("id", name="pk_rotation_rule_sets"),
        sa.UniqueConstraint("rule_version", name="uq_rotation_rule_sets_rule_version"),
    )
    _append_only("rotation_rule_sets")
    op.execute(
        "CREATE TRIGGER rotation_rule_sets_audit AFTER INSERT ON rotation_rule_sets "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )

    op.create_table(
        "rotation_assessments",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("stress", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "stress IS NULL OR stress IN ('normal', 'elevated', 'high', 'crisis')", name="stress"
        ),
        sa.CheckConstraint(
            "reason IN ('month_start', 'defensive_switch', 'carried', 'unavailable')",
            name="reason",
        ),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint(
            "(reason = 'unavailable') = (target IS NULL)", name="target_when_available"
        ),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["rotation_rule_sets.rule_version"],
            name="fk_rotation_assessments_rule_version_rotation_rule_sets",
        ),
        sa.ForeignKeyConstraint(
            ["previous_id"],
            ["rotation_assessments.id"],
            name="fk_rotation_assessments_previous_id_rotation_assessments",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rotation_assessments"),
        sa.UniqueConstraint(
            "known_at", "rule_version", name="uq_rotation_assessments_known_at_rule"
        ),
    )
    _append_only("rotation_assessments")

    op.drop_constraint("uq_signals_instrument_family_time_rule", "signals", type_="unique")
    op.create_unique_constraint(
        "uq_signals_instrument_family_strategy_time_rule",
        "signals",
        ["instrument_id", "family_id", "strategy_id", "generated_at", "rule_version"],
        postgresql_nulls_not_distinct=True,
    )

    _replace(
        "alerts",
        "kind",
        "kind",
        "kind IN ('event', 'level_change', 'regime', 'portfolio', 'rotation')",
    )
    _replace(
        "alerts",
        "kind_fields",
        "kind_fields",
        KIND_FIELDS.format(kinds="'regime', 'portfolio', 'rotation'"),
    )


def downgrade() -> None:
    _replace(
        "alerts", "kind_fields", "kind_fields", KIND_FIELDS.format(kinds="'regime', 'portfolio'")
    )
    _replace("alerts", "kind", "kind", "kind IN ('event', 'level_change', 'regime', 'portfolio')")
    op.drop_constraint("uq_signals_instrument_family_strategy_time_rule", "signals", type_="unique")
    op.create_unique_constraint(
        "uq_signals_instrument_family_time_rule",
        "signals",
        ["instrument_id", "family_id", "generated_at", "rule_version"],
    )
    op.drop_table("rotation_assessments")
    op.drop_table("rotation_rule_sets")
