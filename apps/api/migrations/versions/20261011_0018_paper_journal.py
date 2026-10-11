"""Paper journal (M1.6, ADR-027): signals, thesis_cards and trade_decisions, all append-only.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-11

- signals: a rule's signal (J1). Phase 1 has one source: a buyback state assignment at ACTIVE or
  HIGH-CONVICTION makes one long signal of family 2 for strategy S1. Every signal is paper_only.
  One row per company, family, time and rule version.
- thesis_cards: one version of a Thesis Card written at T = system time (no backdating): thesis,
  3-7 evidence items, each a snapshot of a system row as known at T (J2), up to 5 catalysts, the
  invalidation and the valuation it relies on. A change is a new version of the same card_id.
  Audited on insert.
- trade_decisions: a paper TRADE or an explicit NO TRADE on a card. A TRADE stores the last
  end-of-day close known at T; an exit is a new decision pointing at its entry (one exit each).
  The Phase 1 limits are CHECKs (P1-6): paper mode, no broker, risk check or portfolio snapshot,
  approval state `recorded`, single user. Audited on insert.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
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
        "signals",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("family_id", sa.SmallInteger(), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_ids", _jsonb(), nullable=False),
        sa.Column("source_quality", sa.SmallInteger(), nullable=False),
        sa.Column("evidence_independence", sa.SmallInteger(), nullable=False),
        sa.Column("execution_eligibility", sa.Text(), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("direction IN ('long', 'short', 'neutral')", name="direction"),
        sa.CheckConstraint("execution_eligibility = 'paper_only'", name="paper_only"),
        sa.CheckConstraint("source_quality BETWEEN 1 AND 4", name="source_quality_range"),
        sa.CheckConstraint("evidence_independence >= 0", name="evidence_independence_positive"),
        sa.CheckConstraint("system_time >= generated_at", name="system_time_after_generated_at"),
        sa.ForeignKeyConstraint(
            ["family_id"], ["signal_families.id"], name="fk_signals_family_id_signal_families"
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name="fk_signals_strategy_id_strategies"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_signals_instrument_id_instruments"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signals"),
        sa.UniqueConstraint(
            "instrument_id",
            "family_id",
            "generated_at",
            "rule_version",
            name="uq_signals_instrument_family_time_rule",
        ),
    )
    op.create_index("ix_signals_generated_at", "signals", ["generated_at"])
    _append_only("signals", audited=False)

    op.create_table(
        "thesis_cards",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("evidence", _jsonb(), nullable=False),
        sa.Column("catalysts", _jsonb(), nullable=False),
        sa.Column("invalidation", sa.Text(), nullable=False),
        sa.Column("valuation", _jsonb(), nullable=False),
        sa.Column("signal_ids", _jsonb(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("length(thesis) BETWEEN 1 AND 400", name="thesis_length"),
        sa.CheckConstraint("length(invalidation) BETWEEN 1 AND 500", name="invalidation_length"),
        sa.CheckConstraint("notes IS NULL OR length(notes) <= 2000", name="notes_length"),
        sa.CheckConstraint("jsonb_array_length(evidence) BETWEEN 3 AND 7", name="evidence_count"),
        sa.CheckConstraint("jsonb_array_length(catalysts) <= 5", name="catalyst_count"),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint("user_id = 'steven'", name="single_user"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_thesis_cards_instrument_id_instruments"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_thesis_cards"),
        sa.UniqueConstraint("card_id", "version", name="uq_thesis_cards_card_id_version"),
    )
    _append_only("thesis_cards", audited=True)

    op.create_table(
        "trade_decisions",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("thesis_card_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=True),
        sa.Column("signal_ids", _jsonb(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("order_type", sa.Text(), nullable=True),
        sa.Column("limit_price", sa.Numeric(), nullable=True),
        sa.Column("max_loss", sa.Numeric(), nullable=True),
        sa.Column("no_trade_reason", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("exits_decision_id", sa.Uuid(), nullable=True),
        sa.Column("entry_close", _jsonb(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("broker", sa.Text(), nullable=True),
        sa.Column("risk_check_id", sa.Uuid(), nullable=True),
        sa.Column("portfolio_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("approval_state", sa.Text(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("decision IN ('trade', 'no_trade')", name="decision"),
        sa.CheckConstraint("side IS NULL OR side IN ('buy', 'sell')", name="side"),
        sa.CheckConstraint(
            "order_type IS NULL OR order_type IN ('market', 'limit')", name="order_type"
        ),
        sa.CheckConstraint(
            "no_trade_reason IS NULL OR no_trade_reason IN "
            "('priced_in', 'insufficient_evidence', 'excessive_risk', 'other')",
            name="no_trade_reason",
        ),
        sa.CheckConstraint(
            "(decision = 'trade' AND side IS NOT NULL AND quantity > 0 AND order_type IS NOT NULL"
            " AND no_trade_reason IS NULL AND entry_close IS NOT NULL)"
            " OR (decision = 'no_trade' AND side IS NULL AND quantity IS NULL"
            " AND order_type IS NULL AND exits_decision_id IS NULL"
            " AND no_trade_reason IS NOT NULL)",
            name="decision_fields",
        ),
        sa.CheckConstraint(
            "(order_type = 'limit') = (limit_price IS NOT NULL)", name="limit_price"
        ),
        sa.CheckConstraint("limit_price IS NULL OR limit_price > 0", name="limit_price_positive"),
        sa.CheckConstraint("max_loss IS NULL OR max_loss > 0", name="max_loss_positive"),
        sa.CheckConstraint(
            "no_trade_reason <> 'other' OR note IS NOT NULL", name="other_reason_note"
        ),
        sa.CheckConstraint("note IS NULL OR length(note) <= 1000", name="note_length"),
        sa.CheckConstraint("mode = 'paper'", name="paper_mode"),
        sa.CheckConstraint("broker IS NULL", name="no_broker"),
        sa.CheckConstraint("risk_check_id IS NULL", name="no_risk_check"),
        sa.CheckConstraint("portfolio_snapshot_id IS NULL", name="no_portfolio_snapshot"),
        sa.CheckConstraint("approval_state = 'recorded'", name="approval_state"),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint("user_id = 'steven'", name="single_user"),
        sa.ForeignKeyConstraint(
            ["thesis_card_id"],
            ["thesis_cards.id"],
            name="fk_trade_decisions_thesis_card_id_thesis_cards",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_trade_decisions_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name="fk_trade_decisions_strategy_id_strategies"
        ),
        sa.ForeignKeyConstraint(
            ["exits_decision_id"],
            ["trade_decisions.id"],
            name="fk_trade_decisions_exits_decision_id_trade_decisions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_trade_decisions"),
    )
    op.create_index(
        "uq_trade_decisions_exits_decision_id",
        "trade_decisions",
        ["exits_decision_id"],
        unique=True,
        postgresql_where=sa.text("exits_decision_id IS NOT NULL"),
    )
    _append_only("trade_decisions", audited=True)


def downgrade() -> None:
    op.drop_table("trade_decisions")
    op.drop_table("thesis_cards")
    op.drop_table("signals")
