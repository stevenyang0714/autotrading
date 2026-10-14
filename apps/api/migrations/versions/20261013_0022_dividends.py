"""Cash dividends (M2.2, ADR-030): dividend_events, append-only.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-13

One row per instrument, ex-date and kind (regular or special): `rate` per share as of the
ex-date. Written by the `alpaca.dividends` job from Alpaca corporate actions (2016 on); total
returns reinvest them on the ex-date (domain/factors.py). published_at is the start of the
ex-date in New York.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)


def upgrade() -> None:
    op.create_table(
        "dividend_events",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(), nullable=False),
        sa.Column("special", sa.Boolean(), nullable=False),
        sa.Column("foreign", sa.Boolean(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("payable_date", sa.Date(), nullable=True),
        sa.Column("corporate_action_id", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Provenance (ProvenanceMixin)
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
        sa.CheckConstraint("rate > 0", name="rate_positive"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_dividend_events_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_dividend_events_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"],
            ["source_tiers.tier"],
            name="fk_dividend_events_source_tier_source_tiers",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_dividend_events_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dividend_events"),
        sa.UniqueConstraint(
            "instrument_id", "ex_date", "special", name="uq_dividend_events_instrument_ex_special"
        ),
    )
    op.execute(
        "CREATE TRIGGER dividend_events_append_only BEFORE UPDATE OR DELETE ON dividend_events "
        "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER dividend_events_no_truncate BEFORE TRUNCATE ON dividend_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def downgrade() -> None:
    op.drop_table("dividend_events")
