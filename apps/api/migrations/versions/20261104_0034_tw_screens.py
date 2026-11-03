"""Taiwan listed-stock screens (M3.11, ADR-042): listed_companies, screen_rule_sets,
screen_runs and screen_deliveries.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-04

- listed_companies: the TWSE company file (t187ap03_L) as observed, one row per company and
  change: code, short name, industry code, listing date and whether the file still lists it.
  Append-only and audited; a row is added only when a value differs from the company's latest
  row (SC2).
- screen_rule_sets: one row per released rule_version of config/screen_rules.yaml, with its
  content and sha256 (append-only, audited).
- screen_runs: one evaluation of the Taiwan screens for a session as held at system_time:
  judged (the movers, each screen's readings and watch list) or not judged with its reason
  (SC10). At most one judged run per rule version, market and session. Append-only, not
  audited (like the momentum assessments).
- screen_deliveries: each attempt to push a run's report outside the app, sent or failed; at
  most one `sent` per run and channel. Append-only and audited. Never the chat id, the token
  or the raw reply.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)


def _append_only(table: str, *, audited: bool) -> None:
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


def _provenance() -> list[sa.Column[Any]]:
    return [
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_tier", sa.SmallInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at_precision", sa.Text(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("license_status", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("source_timezone", sa.Text(), nullable=True),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=True),
        sa.Column("raw_payload_sha256", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "listed_companies",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("short_name", sa.Text(), nullable=False),
        sa.Column("industry", sa.Text(), nullable=False),
        sa.Column("listed_on", sa.Date(), nullable=True),
        sa.Column("listed", sa.Boolean(), nullable=False),
        *_provenance(),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("published_at_precision IN ('exact', 'day')", name="precision"),
        sa.CheckConstraint(f"license_status IN ({LICENSE_STATUSES})", name="license_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="effective_range"
        ),
        sa.CheckConstraint("source_url ~ '^https?://'", name="source_url_scheme"),
        sa.CheckConstraint(
            "raw_payload_sha256 IS NULL OR raw_payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="payload_sha256",
        ),
        sa.CheckConstraint(r"code ~ '^\d{4}[0-9A-Z]{0,2}$'", name="code_format"),
        sa.CheckConstraint(r"industry ~ '^\d{2}$'", name="industry_format"),
        sa.CheckConstraint("length(short_name) BETWEEN 1 AND 40", name="short_name_length"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_listed_companies_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_listed_companies_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"],
            ["source_tiers.tier"],
            name="fk_listed_companies_source_tier_source_tiers",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_listed_companies_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_listed_companies"),
    )
    op.create_index(
        "ix_listed_companies_instrument_published",
        "listed_companies",
        ["instrument_id", "published_at"],
    )
    _append_only("listed_companies", audited=True)

    op.create_table(
        "screen_rule_sets",
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
        sa.PrimaryKeyConstraint("id", name="pk_screen_rule_sets"),
        sa.UniqueConstraint("rule_version", name="uq_screen_rule_sets_rule_version"),
    )
    _append_only("screen_rule_sets", audited=True)

    op.create_table(
        "screen_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("session", sa.Date(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("previous_id", sa.Uuid(), nullable=True),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("market IN ('TW')", name="market"),
        sa.CheckConstraint("status IN ('judged', 'not_judged')", name="status"),
        sa.CheckConstraint(
            "(status = 'not_judged') = (reason IS NOT NULL)", name="reason_when_not_judged"
        ),
        sa.CheckConstraint("reason IS NULL OR length(reason) <= 300", name="reason_length"),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.CheckConstraint("backfilled = (system_time > known_at)", name="backfilled_flag"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["screen_rule_sets.rule_version"],
            name="fk_screen_runs_rule_version_screen_rule_sets",
        ),
        sa.ForeignKeyConstraint(
            ["previous_id"],
            ["screen_runs.id"],
            name="fk_screen_runs_previous_id_screen_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_screen_runs"),
    )
    op.create_index(
        "uq_screen_runs_judged",
        "screen_runs",
        ["rule_version", "market", "session"],
        unique=True,
        postgresql_where=sa.text("status = 'judged'"),
    )
    op.create_index("ix_screen_runs_market_session", "screen_runs", ["market", "session"])
    _append_only("screen_runs", audited=False)

    op.create_table(
        "screen_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("error IS NULL OR length(error) <= 300", name="error_length"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["screen_runs.id"], name="fk_screen_deliveries_run_id_screen_runs"
        ),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["delivery_rule_sets.rule_version"],
            name="fk_screen_deliveries_rule_version_delivery_rule_sets",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_screen_deliveries"),
    )
    op.create_index(
        "uq_screen_deliveries_sent",
        "screen_deliveries",
        ["run_id", "channel"],
        unique=True,
        postgresql_where=sa.text("status = 'sent'"),
    )
    _append_only("screen_deliveries", audited=True)


def downgrade() -> None:
    op.drop_index("uq_screen_deliveries_sent", table_name="screen_deliveries")
    op.drop_table("screen_deliveries")
    op.drop_index("ix_screen_runs_market_session", table_name="screen_runs")
    op.drop_index("uq_screen_runs_judged", table_name="screen_runs")
    op.drop_table("screen_runs")
    op.drop_table("screen_rule_sets")
    op.drop_index("ix_listed_companies_instrument_published", table_name="listed_companies")
    op.drop_table("listed_companies")
