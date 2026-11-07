"""Investment policy versions (M3.12, ADR-043 IP2).

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-07

- investment_policies: Steven's investment policy as he writes it on the web app, one row per
  version (1, 2, ...): goals, horizon and risk in his words, the sleeves with their targets,
  bands and members, and his reason for the version. In force from recorded_at until the next
  version. Holdings-side (ADR-041 H4): no rule reads it. Append-only and audited (actor `web`).
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investment_policies",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        sa.CheckConstraint("length(reason) BETWEEN 1 AND 500", name="reason_length"),
        sa.CheckConstraint("user_id = 'steven'", name="single_user"),
        sa.PrimaryKeyConstraint("id", name="pk_investment_policies"),
        sa.UniqueConstraint("version", name="uq_investment_policies_version"),
    )
    op.execute(
        "CREATE TRIGGER investment_policies_append_only BEFORE UPDATE OR DELETE "
        "ON investment_policies FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER investment_policies_no_truncate BEFORE TRUNCATE "
        "ON investment_policies FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )
    op.execute(
        "CREATE TRIGGER investment_policies_audit AFTER INSERT ON investment_policies "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )


def downgrade() -> None:
    op.drop_table("investment_policies")
