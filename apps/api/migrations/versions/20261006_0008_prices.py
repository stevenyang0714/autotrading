"""Prices (M0.7, ADR-017): market_quotes and price_bars as TimescaleDB hypertables.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06

market_quotes: append-only observations (MarketPriceObservation, errata E1), hypertable on
published_at. price_bars: versioned daily bars (raw and split-adjusted), bitemporal like the
other fact tables, hypertable on bar_time. Hypertables need the time column in every unique
index, so both primary keys are (id, time); default hypertable indexes are not created, so the
schema matches the models (alembic check). Row and TRUNCATE triggers work on hypertables
(checked on TimescaleDB 2.30). CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)
FEED_STATUSES = (
    "'live_consolidated', 'live_single_venue', 'delayed', 'end_of_day', 'stale', "
    "'unavailable', 'fixture', 'demo'"
)


def provenance(table: str) -> list[Any]:
    """The provenance columns and checks every observation table carries (ProvenanceMixin)."""
    return [
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_tier", sa.SmallInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=f"fk_{table}_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"], ["source_tiers.tier"], name=f"fk_{table}_source_tier_source_tiers"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=f"fk_{table}_ingestion_run_id_ingestion_runs",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name=f"fk_{table}_instrument_id_instruments"
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "market_quotes",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("bid", sa.Numeric(), nullable=True),
        sa.Column("ask", sa.Numeric(), nullable=True),
        sa.Column("bid_size", sa.BigInteger(), nullable=True),
        sa.Column("ask_size", sa.BigInteger(), nullable=True),
        sa.Column("last", sa.Numeric(), nullable=True),
        sa.Column("last_size", sa.BigInteger(), nullable=True),
        sa.Column("day_open", sa.Numeric(), nullable=True),
        sa.Column("day_high", sa.Numeric(), nullable=True),
        sa.Column("day_low", sa.Numeric(), nullable=True),
        sa.Column("day_volume", sa.BigInteger(), nullable=True),
        sa.Column("prev_close", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feed_status", sa.Text(), nullable=False),
        sa.Column("adjustment_status", sa.Text(), server_default=sa.text("'raw'"), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *provenance("market_quotes"),
        sa.CheckConstraint(f"feed_status IN ({FEED_STATUSES})", name="feed_status"),
        sa.CheckConstraint("adjustment_status = 'raw'", name="adjustment_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        sa.PrimaryKeyConstraint("id", "published_at", name="pk_market_quotes"),
        sa.UniqueConstraint(
            "instrument_id", "published_at", name="uq_market_quotes_instrument_id_published_at"
        ),
    )
    op.create_index(
        "ix_market_quotes_symbol_published_at", "market_quotes", ["symbol", "published_at"]
    )
    op.execute(
        "SELECT create_hypertable('market_quotes', 'published_at', "
        "chunk_time_interval => INTERVAL '7 days', create_default_indexes => false)"
    )
    op.execute(
        "CREATE TRIGGER market_quotes_append_only BEFORE UPDATE OR DELETE ON market_quotes "
        "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER market_quotes_no_truncate BEFORE TRUNCATE ON market_quotes "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )

    op.create_table(
        "price_bars",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("adjustment", sa.Text(), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("vwap", sa.Numeric(), nullable=True),
        sa.Column("trade_count", sa.BigInteger(), nullable=True),
        sa.Column("feed", sa.Text(), nullable=False),
        sa.Column("feed_status", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        *provenance("price_bars"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= recorded_at", name="system_time_order"
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("adjustment IN ('raw', 'split')", name="adjustment"),
        sa.CheckConstraint("feed_status IN ('end_of_day', 'fixture')", name="feed_status"),
        sa.CheckConstraint("close NOT IN ('NaN', 'Infinity', '-Infinity')", name="close_finite"),
        sa.CheckConstraint(
            "revision_reason IS NULL OR revision_reason IN "
            "('restatement', 'revision', 'correction')",
            name="revision_reason",
        ),
        sa.CheckConstraint(
            "(supersedes_id IS NULL) = (revision_reason IS NULL)", name="revision_link"
        ),
        sa.PrimaryKeyConstraint("id", "bar_time", name="pk_price_bars"),
    )
    op.create_index(
        "uq_price_bars_key_version",
        "price_bars",
        ["instrument_id", "adjustment", "bar_time", "version"],
        unique=True,
    )
    op.create_index(
        "uq_price_bars_current_key_published",
        "price_bars",
        ["instrument_id", "adjustment", "bar_time", "published_at"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index("ix_price_bars_symbol_bar_date", "price_bars", ["symbol", "bar_date"])
    op.execute(
        "SELECT create_hypertable('price_bars', 'bar_time', "
        "chunk_time_interval => INTERVAL '1 year', create_default_indexes => false)"
    )
    op.execute(
        "CREATE TRIGGER price_bars_system_time BEFORE INSERT ON price_bars "
        "FOR EACH ROW EXECUTE FUNCTION fact_before_insert()"
    )
    op.execute(
        "CREATE TRIGGER price_bars_append_only BEFORE UPDATE OR DELETE ON price_bars "
        "FOR EACH ROW EXECUTE FUNCTION fact_before_update_delete()"
    )
    op.execute(
        "CREATE TRIGGER price_bars_no_truncate BEFORE TRUNCATE ON price_bars "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )
    op.execute(
        "CREATE TRIGGER price_bars_audit AFTER UPDATE ON price_bars "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change('fact')"
    )


def downgrade() -> None:
    op.drop_table("price_bars")
    op.drop_table("market_quotes")
