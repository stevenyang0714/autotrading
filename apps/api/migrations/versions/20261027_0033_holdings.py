"""Holdings ledger and daily holdings snapshots (M3.10, ADR-041 H1, H2).

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-27

- holding_entries: Steven's real holdings as he records them from the web app, kept apart from
  the paper portfolio (H4): buys, sells, cash dividends, deposits, withdrawals and fees, each on
  a broker account label, in USD (US listings) or TWD (TWSE listings). Append-only and audited
  (actor `web`): a mistake is corrected by a reversal entry pointing at it (one each), never by
  an update. The trade date is never after the day it was recorded (Taipei date, the latest of
  the two markets). Nothing here can send an order: there is no order, broker or execution
  column.
- holding_snapshots: the holdings valued at a time T (known_at) as the database held them at
  system_time under one valuation version: USD equity (null when a TWD amount had no exchange
  rate), cash by currency, the rate used and the whole document with every position and flag.
  One row per T, system time and version. Append-only.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"
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


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "holding_entries",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("price", sa.Numeric(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("fee", sa.Numeric(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('buy', 'sell', 'dividend', 'deposit', 'withdrawal', 'fee', 'reversal')",
            name="kind",
        ),
        sa.CheckConstraint("currency IN ('USD', 'TWD')", name="currency"),
        sa.CheckConstraint("market IS NULL OR market IN ('US', 'TW')", name="market"),
        sa.CheckConstraint(
            "market IS NULL OR (market = 'US' AND currency = 'USD') "
            "OR (market = 'TW' AND currency = 'TWD')",
            name="market_currency",
        ),
        sa.CheckConstraint(
            "(kind IN ('buy', 'sell') AND market IS NOT NULL AND instrument_id IS NOT NULL"
            " AND symbol IS NOT NULL AND coalesce(quantity, 0) > 0 AND coalesce(price, 0) > 0"
            " AND amount IS NULL"
            " AND (fee IS NULL OR fee >= 0) AND reverses_id IS NULL)"
            " OR (kind = 'dividend' AND market IS NOT NULL AND instrument_id IS NOT NULL"
            " AND symbol IS NOT NULL AND quantity IS NULL AND price IS NULL"
            " AND coalesce(amount, 0) > 0"
            " AND fee IS NULL AND reverses_id IS NULL)"
            " OR (kind IN ('deposit', 'withdrawal', 'fee') AND market IS NULL"
            " AND instrument_id IS NULL AND symbol IS NULL AND quantity IS NULL"
            " AND price IS NULL AND coalesce(amount, 0) > 0 AND fee IS NULL"
            " AND reverses_id IS NULL)"
            " OR (kind = 'reversal' AND reverses_id IS NOT NULL AND market IS NULL"
            " AND instrument_id IS NULL AND symbol IS NULL AND quantity IS NULL"
            " AND price IS NULL AND amount IS NULL AND fee IS NULL)",
            name="kind_fields",
        ),
        sa.CheckConstraint("length(account) BETWEEN 1 AND 40", name="account_length"),
        sa.CheckConstraint("symbol IS NULL OR symbol ~ '^[A-Z0-9.]{1,10}$'", name="symbol_format"),
        sa.CheckConstraint("note IS NULL OR length(note) <= 500", name="note_length"),
        sa.CheckConstraint(
            "trade_date <= (recorded_at AT TIME ZONE 'Asia/Taipei')::date",
            name="trade_date_not_future",
        ),
        sa.CheckConstraint("user_id = 'steven'", name="single_user"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_holding_entries_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_id"],
            ["holding_entries.id"],
            name="fk_holding_entries_reverses_id_holding_entries",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_holding_entries"),
    )
    op.create_index(
        "uq_holding_entries_reverses_id",
        "holding_entries",
        ["reverses_id"],
        unique=True,
        postgresql_where=sa.text("reverses_id IS NOT NULL"),
    )
    _append_only("holding_entries", audited=True)

    op.create_table(
        "holding_snapshots",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valuation_version", sa.Text(), nullable=False),
        sa.Column("equity_usd", sa.Numeric(), nullable=True),
        sa.Column("cash", _jsonb(), nullable=False),
        sa.Column("fx", _jsonb(), nullable=True),
        sa.Column("positions", sa.SmallInteger(), nullable=False),
        sa.Column("holdings", _jsonb(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("trigger IN ('schedule', 'manual')", name="trigger"),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint("positions >= 0", name="positions_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_holding_snapshots"),
        sa.UniqueConstraint(
            "known_at", "system_time", "valuation_version", name="uq_holding_snapshots_point"
        ),
    )
    op.create_index("ix_holding_snapshots_known_at", "holding_snapshots", ["known_at"])
    _append_only("holding_snapshots", audited=False)


def downgrade() -> None:
    op.drop_table("holding_snapshots")
    op.drop_table("holding_entries")
