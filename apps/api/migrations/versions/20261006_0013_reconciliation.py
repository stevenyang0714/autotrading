"""Filing reconciliation (M1.1, ADR-021): filing_reconciliations and reconciliation_items.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-06

One row per filing checked against its own XBRL instance at a methodology version, with its
counts, and one row per check. Both append-only: a new methodology version adds rows.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "filing_reconciliations",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("accession_number", sa.Text(), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("filing_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_payload_sha256", sa.Text(), nullable=False),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column("checked", sa.Integer(), nullable=False),
        sa.Column("matched", sa.Integer(), nullable=False),
        sa.Column("mismatched", sa.Integer(), nullable=False),
        sa.Column("missing", sa.Integer(), nullable=False),
        sa.Column("extra", sa.Integer(), nullable=False),
        sa.Column("restated_later", sa.Integer(), nullable=False),
        sa.Column("checks_failed", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('pass', 'fail')", name="status"),
        sa.CheckConstraint("source_url ~ '^https://'", name="source_url_scheme"),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name="fk_filing_reconciliations_entity_id_entities"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_filing_reconciliations_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_filing_reconciliations"),
        sa.UniqueConstraint(
            "entity_id",
            "accession_number",
            "methodology_version",
            name="uq_filing_reconciliations_filing_version",
        ),
    )
    op.create_index(
        "ix_filing_reconciliations_entity_id_form", "filing_reconciliations", ["entity_id", "form"]
    )
    op.create_table(
        "reconciliation_items",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("reconciliation_id", sa.Uuid(), nullable=False),
        sa.Column("check_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("metric_id", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("filing_value", sa.Numeric(), nullable=True),
        sa.Column("stored_value", sa.Numeric(), nullable=True),
        sa.Column("current_value", sa.Numeric(), nullable=True),
        sa.Column("stored_accession", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "check_kind IN ('fact', 'identity', 'quarter', 'split')", name="check_kind"
        ),
        sa.CheckConstraint(
            "status IN ('match', 'mismatch', 'missing', 'extra', 'restated_later', 'ok', 'fail', "
            "'flag')",
            name="status",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["filing_reconciliations.id"],
            name="fk_reconciliation_items_reconciliation_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reconciliation_items"),
    )
    op.create_index(
        "ix_reconciliation_items_reconciliation_id", "reconciliation_items", ["reconciliation_id"]
    )
    for table in ("filing_reconciliations", "reconciliation_items"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
        )


def downgrade() -> None:
    op.drop_table("reconciliation_items")
    op.drop_table("filing_reconciliations")
