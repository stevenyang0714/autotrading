"""Valuation assumptions (M1.3a, ADR-023): one row per version of a company's fair-value
assumptions.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08

Saved by Steven on the instrument page; the first table the web app writes to. Append-only:
a change is a new version (instrument, version unique), so a valuation made with an earlier
version stays reproducible. Audited on insert (who saved which version, when).
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valuation_assumptions",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("length(reason) BETWEEN 1 AND 500", name="reason_length"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_valuation_assumptions_instrument_id_instruments",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_valuation_assumptions"),
        sa.UniqueConstraint(
            "instrument_id", "version", name="uq_valuation_assumptions_instrument_id_version"
        ),
    )
    op.execute(
        "CREATE TRIGGER valuation_assumptions_append_only BEFORE UPDATE OR DELETE "
        "ON valuation_assumptions FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER valuation_assumptions_no_truncate BEFORE TRUNCATE "
        "ON valuation_assumptions FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )
    op.execute(
        "CREATE TRIGGER valuation_assumptions_audit AFTER INSERT ON valuation_assumptions "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )


def downgrade() -> None:
    op.drop_table("valuation_assumptions")
