"""Macro series registry and ALFRED observations with vintages (M0.6, ADR-015).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06

macro_series is mutable and audited (rows from config/macro_series.yaml, metadata from FRED).
macro_observations is an append-only bitemporal fact table with the same triggers as
financial_facts. CHECK constraints are named by suffix only; the naming convention adds the
`ck_<table>_` prefix.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)
FREQUENCIES = "'D', 'W', 'BW', 'M', 'Q', 'SA', 'A'"
REVISION_REASONS = "'restatement', 'revision', 'correction'"


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("term_id", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("100"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("units", sa.Text(), nullable=True),
        sa.Column("units_short", sa.Text(), nullable=True),
        sa.Column("frequency", sa.Text(), nullable=True),
        sa.Column("frequency_short", sa.Text(), nullable=True),
        sa.Column("seasonal_adjustment_short", sa.Text(), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("id ~ '^[A-Z0-9_]+$'", name="id_format"),
        sa.CheckConstraint("term_id ~ '^[a-z][a-z0-9_]*$'", name="term_id_format"),
        sa.CheckConstraint(
            f"frequency_short IS NULL OR frequency_short IN ({FREQUENCIES})",
            name="frequency_short",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_macro_series_source_id_sources"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_macro_series"),
    )
    op.execute(
        "CREATE TRIGGER macro_series_touch BEFORE UPDATE ON macro_series FOR EACH ROW "
        "WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION touch_mutable_row()"
    )
    op.execute(
        "CREATE TRIGGER macro_series_audit AFTER INSERT OR UPDATE OR DELETE ON macro_series "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )

    op.create_table(
        "macro_observations",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("series_id", sa.Text(), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("vintage", sa.Date(), nullable=False),
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
            ["series_id"], ["macro_series.id"], name="fk_macro_observations_series_id_macro_series"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["macro_observations.id"],
            name="fk_macro_observations_supersedes_id_macro_observations",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_macro_observations_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"],
            ["source_tiers.tier"],
            name="fk_macro_observations_source_tier_source_tiers",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_macro_observations_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_macro_observations"),
    )
    op.create_index(
        "uq_macro_observations_key_version",
        "macro_observations",
        ["series_id", "observation_date", "version"],
        unique=True,
    )
    op.create_index(
        "uq_macro_observations_current_key_published",
        "macro_observations",
        ["series_id", "observation_date", "published_at"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    table = "macro_observations"
    op.execute(
        f"CREATE TRIGGER {table}_system_time BEFORE INSERT ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION fact_before_insert()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION fact_before_update_delete()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_audit AFTER UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change('fact')"
    )


def downgrade() -> None:
    op.drop_table("macro_observations")
    op.drop_table("macro_series")
