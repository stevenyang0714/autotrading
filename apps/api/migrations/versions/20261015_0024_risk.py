"""Paper portfolio and risk checks (M2.3, ADR-031): risk_rule_sets, portfolio_snapshots and
risk_checks, append-only; every paper TRADE entry cites a passed risk check.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-15

- risk_rule_sets: one row per released rule_version of config/risk_rules.yaml, loaded by
  `make migrate` with the sha256 of its content; audited on insert.
- portfolio_snapshots: the paper portfolio at a time T as held at system_time, under one rule
  version; one row per T, system time and rule version.
- risk_checks: a proposed paper trade against every limit, with its verdict; audited on insert
  except the daily standard checks (one per company and T).
- trade_decisions: the Phase 1 checks `no_risk_check` and `no_portfolio_snapshot` give way to
  foreign keys (P2-7); a TRADE entry needs a risk check, and a trigger refuses one that did not
  pass or was for another trade. Paper mode, no broker, `approval_state = 'recorded'` and one
  user stay.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PORTFOLIO_TRIGGERS = "'schedule', 'manual', 'backfill', 'replay', 'trade', 'on_demand', 'standard'"

REQUIRE_PASSED = """
CREATE OR REPLACE FUNCTION require_passed_risk_check() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    checked risk_checks%ROWTYPE;
BEGIN
    IF NEW.decision <> 'trade' OR NEW.exits_decision_id IS NOT NULL THEN
        RETURN NEW;
    END IF;
    SELECT * INTO checked FROM risk_checks WHERE id = NEW.risk_check_id;
    IF NOT FOUND OR checked.verdict <> 'pass' THEN
        RAISE EXCEPTION 'a paper TRADE needs a passed risk check (ADR-031)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF checked.instrument_id <> NEW.instrument_id OR checked.side <> NEW.side
        OR checked.quantity <> NEW.quantity THEN
        RAISE EXCEPTION 'the risk check was for another trade (ADR-031)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


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
        "risk_rule_sets",
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
        sa.PrimaryKeyConstraint("id", name="pk_risk_rule_sets"),
        sa.UniqueConstraint("rule_version", name="uq_risk_rule_sets_rule_version"),
    )
    _append_only("risk_rule_sets")
    op.execute(
        "CREATE TRIGGER risk_rule_sets_audit AFTER INSERT ON risk_rule_sets "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("equity", sa.Numeric(), nullable=False),
        sa.Column("gross", sa.Numeric(), nullable=False),
        sa.Column("net", sa.Numeric(), nullable=False),
        sa.Column("drawdown_pct", sa.Numeric(), nullable=False),
        sa.Column("positions", sa.SmallInteger(), nullable=False),
        sa.Column("portfolio", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"trigger IN ({PORTFOLIO_TRIGGERS})", name="trigger"),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint("drawdown_pct >= 0", name="drawdown_nonnegative"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["risk_rule_sets.rule_version"],
            name="fk_portfolio_snapshots_rule_version_risk_rule_sets",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_portfolio_snapshots"),
        sa.UniqueConstraint(
            "known_at", "system_time", "rule_version", name="uq_portfolio_snapshots_point"
        ),
    )
    _append_only("portfolio_snapshots")

    op.create_table(
        "risk_checks",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("max_loss", sa.Numeric(), nullable=True),
        sa.Column("price", sa.Numeric(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("portfolio_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("risk_check", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("trigger IN ('trade', 'on_demand', 'standard')", name="trigger"),
        sa.CheckConstraint("verdict IN ('pass', 'veto')", name="verdict"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="side"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("max_loss IS NULL OR max_loss > 0", name="max_loss_positive"),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["risk_rule_sets.rule_version"],
            name="fk_risk_checks_rule_version_risk_rule_sets",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_risk_checks_instrument_id_instruments"
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_id"],
            ["portfolio_snapshots.id"],
            name="fk_risk_checks_portfolio_snapshot_id_portfolio_snapshots",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_risk_checks"),
    )
    op.create_index(
        "uq_risk_checks_standard",
        "risk_checks",
        ["instrument_id", "known_at", "rule_version"],
        unique=True,
        postgresql_where=sa.text("trigger = 'standard'"),
    )
    op.create_index("ix_risk_checks_known_at", "risk_checks", ["known_at"])
    _append_only("risk_checks")
    op.execute(
        "CREATE TRIGGER risk_checks_audit AFTER INSERT ON risk_checks FOR EACH ROW "
        "WHEN (NEW.trigger <> 'standard') EXECUTE FUNCTION audit_row_change()"
    )

    op.drop_constraint(op.f("ck_trade_decisions_no_risk_check"), "trade_decisions", type_="check")
    op.drop_constraint(
        op.f("ck_trade_decisions_no_portfolio_snapshot"), "trade_decisions", type_="check"
    )
    op.create_check_constraint(
        "entry_risk_check",
        "trade_decisions",
        "decision <> 'trade' OR exits_decision_id IS NOT NULL OR risk_check_id IS NOT NULL",
    )
    op.create_check_constraint(
        "risk_check_on_entries",
        "trade_decisions",
        "risk_check_id IS NULL OR (decision = 'trade' AND exits_decision_id IS NULL)",
    )
    op.create_foreign_key(
        "fk_trade_decisions_risk_check_id_risk_checks",
        "trade_decisions",
        "risk_checks",
        ["risk_check_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_trade_decisions_portfolio_snapshot_id_portfolio_snapshots",
        "trade_decisions",
        "portfolio_snapshots",
        ["portfolio_snapshot_id"],
        ["id"],
    )
    op.execute(REQUIRE_PASSED)
    op.execute(
        "CREATE TRIGGER trade_decisions_risk_check BEFORE INSERT ON trade_decisions "
        "FOR EACH ROW EXECUTE FUNCTION require_passed_risk_check()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trade_decisions_risk_check ON trade_decisions")
    op.execute("DROP FUNCTION require_passed_risk_check()")
    op.drop_constraint(
        "fk_trade_decisions_portfolio_snapshot_id_portfolio_snapshots",
        "trade_decisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_trade_decisions_risk_check_id_risk_checks", "trade_decisions", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("ck_trade_decisions_risk_check_on_entries"), "trade_decisions", type_="check"
    )
    op.drop_constraint(
        op.f("ck_trade_decisions_entry_risk_check"), "trade_decisions", type_="check"
    )
    op.create_check_constraint(
        "no_portfolio_snapshot", "trade_decisions", "portfolio_snapshot_id IS NULL"
    )
    op.create_check_constraint("no_risk_check", "trade_decisions", "risk_check_id IS NULL")
    op.drop_table("risk_checks")
    op.drop_table("portfolio_snapshots")
    op.drop_table("risk_rule_sets")
