"""Alert delivery to Telegram (M3.0b, ADR-037): delivery_rule_sets and alert_deliveries, both
append-only and audited; alerts may be a new S4 momentum target.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-20

- delivery_rule_sets: one row per released rule_version of config/delivery_rules.yaml, loaded
  by `make migrate` with the sha256 of its content; audited on insert.
- alert_deliveries: each attempt to push an alert outside the app, sent (with the channel's
  message id) or failed (with a cleaned reason); at most one `sent` per alert and channel.
  Never the chat id, the token or the raw reply.
- alerts: kind `momentum`, a new S4 target (alert rules 0.6.0); like `rotation`, no company.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND_FIELDS = (
    "(kind = 'level_change' AND direction IS NOT NULL AND assessment_id IS NOT NULL"
    " AND instrument_id IS NOT NULL)"
    " OR (kind = 'event' AND direction IS NULL AND level = 0 AND instrument_id IS NOT NULL)"
    " OR (kind IN ({kinds}) AND direction IS NOT NULL"
    " AND assessment_id IS NULL AND instrument_id IS NULL AND ticker IS NULL)"
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


def _replace(table: str, old: str, new: str, sql: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{old}"), table, type_="check")
    op.create_check_constraint(new, table, sql)


def upgrade() -> None:
    op.create_table(
        "delivery_rule_sets",
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
        sa.PrimaryKeyConstraint("id", name="pk_delivery_rule_sets"),
        sa.UniqueConstraint("rule_version", name="uq_delivery_rule_sets_rule_version"),
    )
    _append_only("delivery_rule_sets", audited=True)

    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
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
        sa.CheckConstraint("error IS NULL OR length(error) <= 300", name="error_length"),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["alerts.id"], name="fk_alert_deliveries_alert_id_alerts"
        ),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["delivery_rule_sets.rule_version"],
            name="fk_alert_deliveries_rule_version_delivery_rule_sets",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alert_deliveries"),
    )
    op.create_index(
        "uq_alert_deliveries_sent",
        "alert_deliveries",
        ["alert_id", "channel"],
        unique=True,
        postgresql_where=sa.text("status = 'sent'"),
    )
    op.create_index("ix_alert_deliveries_alert_id", "alert_deliveries", ["alert_id"])
    _append_only("alert_deliveries", audited=True)

    _replace(
        "alerts",
        "kind",
        "kind",
        "kind IN ('event', 'level_change', 'regime', 'portfolio', 'rotation', 'momentum')",
    )
    _replace(
        "alerts",
        "kind_fields",
        "kind_fields",
        KIND_FIELDS.format(kinds="'regime', 'portfolio', 'rotation', 'momentum'"),
    )


def downgrade() -> None:
    _replace(
        "alerts",
        "kind_fields",
        "kind_fields",
        KIND_FIELDS.format(kinds="'regime', 'portfolio', 'rotation'"),
    )
    _replace(
        "alerts",
        "kind",
        "kind",
        "kind IN ('event', 'level_change', 'regime', 'portfolio', 'rotation')",
    )
    op.drop_index("ix_alert_deliveries_alert_id", table_name="alert_deliveries")
    op.drop_index("uq_alert_deliveries_sent", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
    op.drop_table("delivery_rule_sets")
