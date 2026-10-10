"""Buyback states (M1.4b, ADR-025): rule sets and state assignments, both append-only.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10

- buyback_rule_sets: one row per released rule_version of config/buyback_rules.yaml, loaded by
  `make migrate` with the sha256 of its content; a changed content under a released version is
  refused (config_sync). Audited on insert.
- buyback_state_assignments: one evaluation of one company at a time T (known_at) as the
  database held it at system_time, under one rule version: the state, the score and the whole
  assessment (every condition's value, threshold, inputs and evidence). One row per company,
  T and rule version. TRADE-READY is refused: it is unreachable in Phase 1 (P1-4).
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _append_only(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
        f"ON {table} FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE "
        f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def upgrade() -> None:
    op.create_table(
        "buyback_rule_sets",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("approved", sa.Date(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(r"rule_version ~ '^\d+\.\d+\.\d+$'", name="rule_version_format"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        sa.PrimaryKeyConstraint("id", name="pk_buyback_rule_sets"),
        sa.UniqueConstraint("rule_version", name="uq_buyback_rule_sets_rule_version"),
    )
    _append_only("buyback_rule_sets")
    op.execute(
        "CREATE TRIGGER buyback_rule_sets_audit AFTER INSERT ON buyback_rule_sets "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )

    op.create_table(
        "buyback_state_assignments",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("state IN ('none', 'watch', 'active', 'high_conviction')", name="state"),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_buyback_state_assignments_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["buyback_rule_sets.rule_version"],
            name="fk_buyback_state_assignments_rule_version_buyback_rule_sets",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_buyback_state_assignments"),
        sa.UniqueConstraint(
            "instrument_id",
            "known_at",
            "rule_version",
            name="uq_buyback_state_assignments_instrument_known_at_rule",
        ),
    )
    op.create_index(
        "ix_buyback_state_assignments_rule_version_known_at",
        "buyback_state_assignments",
        ["rule_version", "known_at"],
    )
    _append_only("buyback_state_assignments")


def downgrade() -> None:
    op.drop_table("buyback_state_assignments")
    op.drop_table("buyback_rule_sets")
