"""Price, trend and factors (M2.2, ADR-030): factor_definition_sets and factor_snapshots,
append-only.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-13

- factor_definition_sets: one row per released definition_version of
  config/factor_definitions.yaml, loaded by `make migrate` with the sha256 of its content;
  audited on insert.
- factor_snapshots: one instrument's measures at a time T as the database held them at
  system_time, under one definition version: each measure's value (`measure_values`) and the
  whole document with every input (`snapshot`). One row per instrument, T and definition
  version.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "factor_definition_sets",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("definition_version", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("released", sa.Date(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            r"definition_version ~ '^\d+\.\d+\.\d+$'", name="definition_version_format"
        ),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        sa.PrimaryKeyConstraint("id", name="pk_factor_definition_sets"),
        sa.UniqueConstraint("definition_version", name="uq_factor_definition_sets_version"),
    )
    _append_only("factor_definition_sets", audited=True)

    op.create_table(
        "factor_snapshots",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("definition_version", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("last_close", sa.Date(), nullable=True),
        sa.Column("feed_status", sa.Text(), nullable=True),
        sa.Column("measure_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("scope IN ('price', 'all')", name="scope"),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_factor_snapshots_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["definition_version"],
            ["factor_definition_sets.definition_version"],
            name="fk_factor_snapshots_definition_version_factor_definition_sets",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_factor_snapshots"),
        sa.UniqueConstraint(
            "instrument_id", "known_at", "definition_version", name="uq_factor_snapshots_key"
        ),
    )
    op.create_index(
        "ix_factor_snapshots_instrument_version_known_at",
        "factor_snapshots",
        ["instrument_id", "definition_version", "known_at"],
    )
    _append_only("factor_snapshots", audited=False)


def downgrade() -> None:
    op.drop_table("factor_snapshots")
    op.drop_table("factor_definition_sets")
