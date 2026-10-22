"""Exchange-published measures of the Taiwan universe (M3.7, ADR-039 TW7).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-22

exchange_measures is an append-only bitemporal fact table with the same triggers as
macro_observations: one value per instrument, measure and session, as the TWSE OpenAPI
published it (price change, trade value, P/E, P/B, dividend yield, margin and short balances).
CHECK constraints are named by suffix only; the naming convention adds the `ck_<table>_`
prefix.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)
REVISION_REASONS = "'restatement', 'revision', 'correction'"
TABLE = "exchange_measures"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("measure_id", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("data_mode", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        # provenance
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
        # system time
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= recorded_at", name="system_time_order"
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("measure_id ~ '^[a-z][a-z0-9_]*$'", name="measure_id_format"),
        sa.CheckConstraint("unit IN ('TWD', 'percent', 'x', 'lots')", name="unit"),
        sa.CheckConstraint("data_mode IN ('live', 'fixture')", name="data_mode"),
        sa.CheckConstraint("value NOT IN ('NaN', 'Infinity', '-Infinity')", name="value_finite"),
        sa.CheckConstraint(
            f"revision_reason IS NULL OR revision_reason IN ({REVISION_REASONS})",
            name="revision_reason",
        ),
        sa.CheckConstraint(
            "(supersedes_id IS NULL) = (revision_reason IS NULL)",
            name="revision_link",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_exchange_measures_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["exchange_measures.id"],
            name="fk_exchange_measures_supersedes_id_exchange_measures",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_exchange_measures_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"],
            ["source_tiers.tier"],
            name="fk_exchange_measures_source_tier_source_tiers",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_exchange_measures_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exchange_measures"),
    )
    op.create_index(
        "uq_exchange_measures_key_version",
        TABLE,
        ["instrument_id", "measure_id", "session_date", "version"],
        unique=True,
    )
    op.create_index(
        "uq_exchange_measures_current_key_published",
        TABLE,
        ["instrument_id", "measure_id", "session_date", "published_at"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_system_time BEFORE INSERT ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION fact_before_insert()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION fact_before_update_delete()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_no_truncate BEFORE TRUNCATE ON {TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_audit AFTER UPDATE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change('fact')"
    )


def downgrade() -> None:
    op.drop_table(TABLE)
