"""Backtests (M2.5, ADR-033): momentum_rule_sets, backtest_rule_sets and backtest_runs,
append-only.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-17

- momentum_rule_sets: one row per released rule_version of config/momentum_rules.yaml (S4),
  loaded by `make migrate` with the sha256 of its content; audited on insert.
- backtest_rule_sets: the same for config/backtest_rules.yaml (fills, costs, folds).
- backtest_runs: one strategy's backtest at a time T as the database held it at system_time,
  under one backtest rule version and one strategy rule version. Performance is withheld until
  OD-7 is decided: `performance_reported` must be false.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
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


def _rule_sets(table: str) -> None:
    op.create_table(
        table,
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
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("rule_version", name=f"uq_{table}_rule_version"),
    )
    _append_only(table)
    op.execute(
        f"CREATE TRIGGER {table}_audit AFTER INSERT ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )


def upgrade() -> None:
    _rule_sets("momentum_rule_sets")
    _rule_sets("backtest_rule_sets")
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("strategy_rule_version", sa.Text(), nullable=False),
        sa.Column("start", sa.Date(), nullable=True),
        sa.Column("end", sa.Date(), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("performance_reported", sa.Boolean(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint("performance_reported = false", name="performance_withheld"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["backtest_rule_sets.rule_version"],
            name="fk_backtest_runs_rule_version_backtest_rule_sets",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name="fk_backtest_runs_strategy_id_strategies"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_runs"),
        sa.UniqueConstraint(
            "strategy_id",
            "known_at",
            "rule_version",
            "strategy_rule_version",
            name="uq_backtest_runs_point",
        ),
    )
    op.create_index("ix_backtest_runs_known_at", "backtest_runs", ["known_at"])
    _append_only("backtest_runs")


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_known_at", table_name="backtest_runs")
    op.drop_table("backtest_runs")
    op.drop_table("backtest_rule_sets")
    op.drop_table("momentum_rule_sets")
