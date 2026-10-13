"""Macro regime (M2.1, ADR-029): regime_rule_sets and regime_assessments, append-only; alerts
may be market-wide (kind `regime`, no company).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-12

- regime_rule_sets: one row per released rule_version of config/regime_rules.yaml, loaded by
  `make migrate` with the sha256 of its content; audited on insert.
- regime_assessments: the five dimensions, quadrant, stress flags and state at a time T as the
  database held it at system_time, under one rule version; one row per T and rule version.
- alerts: instrument_id and ticker become nullable for kind `regime` (a change of the stress
  state); event and level-change alerts still need their company (CHECK kind_fields).
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KIND_FIELDS = (
    "(kind = 'level_change' AND direction IS NOT NULL AND assessment_id IS NOT NULL)"
    " OR (kind = 'event' AND direction IS NULL AND level = 0)"
)
NEW_KIND_FIELDS = (
    "(kind = 'level_change' AND direction IS NOT NULL AND assessment_id IS NOT NULL"
    " AND instrument_id IS NOT NULL)"
    " OR (kind = 'event' AND direction IS NULL AND level = 0 AND instrument_id IS NOT NULL)"
    " OR (kind = 'regime' AND direction IS NOT NULL AND assessment_id IS NULL"
    " AND instrument_id IS NULL AND ticker IS NULL)"
)


def _append_only(table: str, audited: bool) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
        f"ON {table} FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE "
        f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )
    if audited:
        op.execute(
            f"CREATE TRIGGER {table}_audit AFTER INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
        )


def upgrade() -> None:
    op.create_table(
        "regime_rule_sets",
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
        sa.PrimaryKeyConstraint("id", name="pk_regime_rule_sets"),
        sa.UniqueConstraint("rule_version", name="uq_regime_rule_sets_rule_version"),
    )
    _append_only("regime_rule_sets", audited=True)

    op.create_table(
        "regime_assessments",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("stress", sa.Text(), nullable=True),
        sa.Column("quadrant", sa.Text(), nullable=True),
        sa.Column("flags_on", sa.SmallInteger(), nullable=False),
        sa.Column("flags_available", sa.SmallInteger(), nullable=False),
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
            "quadrant IS NULL OR quadrant IN "
            "('goldilocks', 'reflation', 'stagflation', 'disinflationary_slowdown')",
            name="quadrant",
        ),
        sa.CheckConstraint("flags_on BETWEEN 0 AND flags_available", name="flags_on_range"),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["regime_rule_sets.rule_version"],
            name="fk_regime_assessments_rule_version_regime_rule_sets",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_regime_assessments"),
        sa.UniqueConstraint("known_at", "rule_version", name="uq_regime_assessments_known_at_rule"),
    )
    _append_only("regime_assessments", audited=False)

    op.alter_column("alerts", "instrument_id", nullable=True)
    op.alter_column("alerts", "ticker", nullable=True)
    op.drop_constraint(op.f("ck_alerts_kind"), "alerts", type_="check")
    op.create_check_constraint("kind", "alerts", "kind IN ('event', 'level_change', 'regime')")
    op.drop_constraint(op.f("ck_alerts_kind_fields"), "alerts", type_="check")
    op.create_check_constraint("kind_fields", "alerts", NEW_KIND_FIELDS)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_alerts_kind_fields"), "alerts", type_="check")
    op.create_check_constraint("kind_fields", "alerts", OLD_KIND_FIELDS)
    op.drop_constraint(op.f("ck_alerts_kind"), "alerts", type_="check")
    op.create_check_constraint("kind", "alerts", "kind IN ('event', 'level_change')")
    op.alter_column("alerts", "ticker", nullable=False)
    op.alter_column("alerts", "instrument_id", nullable=False)
    op.drop_table("regime_assessments")
    op.drop_table("regime_rule_sets")
