"""The weekly digest of rule candidates (M3.0c, ADR-038): digest_deliveries, append-only and
audited.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-21

- digest_deliveries: each attempt to push the week's digest outside the app, sent (with the
  number of messages and the first message id) or failed (with a cleaned reason); at most one
  `sent` per channel and week (the Monday it is for). Never the chat id, the token or the raw
  reply.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digest_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("messages", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("channel IN ('telegram')", name="channel"),
        sa.CheckConstraint("status IN ('sent', 'failed')", name="status"),
        sa.CheckConstraint(
            "(status = 'sent') = (message_id IS NOT NULL)", name="message_when_sent"
        ),
        sa.CheckConstraint("messages >= 0", name="messages_count"),
        sa.CheckConstraint("extract(isodow FROM week) = 1", name="week_is_monday"),
        sa.CheckConstraint("error IS NULL OR length(error) <= 300", name="error_length"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["delivery_rule_sets.rule_version"],
            name="fk_digest_deliveries_rule_version_delivery_rule_sets",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_digest_deliveries"),
    )
    op.create_index(
        "uq_digest_deliveries_sent",
        "digest_deliveries",
        ["channel", "week"],
        unique=True,
        postgresql_where=sa.text("status = 'sent'"),
    )
    for trigger, timing, function in (
        ("append_only", "BEFORE UPDATE OR DELETE", "forbid_row_change()"),
        ("audit", "AFTER INSERT", "audit_row_change()"),
    ):
        op.execute(
            f"CREATE TRIGGER digest_deliveries_{trigger} {timing} ON digest_deliveries "
            f"FOR EACH ROW EXECUTE FUNCTION {function}"
        )
    op.execute(
        "CREATE TRIGGER digest_deliveries_no_truncate BEFORE TRUNCATE ON digest_deliveries "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def downgrade() -> None:
    op.drop_index("uq_digest_deliveries_sent", table_name="digest_deliveries")
    op.drop_table("digest_deliveries")
