"""SEC EDGAR (M0.5): filings index, XBRL concept on facts, conflicted-row count on runs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05

filings is append-only like raw_payloads: no UPDATE, DELETE or TRUNCATE. It is not audited
per row (JPMorgan alone lists about 170k filings); ingestion_run_id links each row to its run.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column("rows_conflicted", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("financial_facts", sa.Column("source_concept", sa.Text(), nullable=True))

    op.create_table(
        "filings",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("cik", sa.Text(), nullable=False),
        sa.Column("accession_number", sa.Text(), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("primary_document", sa.Text(), nullable=True),
        sa.Column("primary_doc_description", sa.Text(), nullable=True),
        sa.Column("items", sa.Text(), nullable=True),
        sa.Column("is_xbrl", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_inline_xbrl", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "published_at_precision IN ('exact', 'day')", name="ck_filings_precision"
        ),
        sa.CheckConstraint(
            f"license_status IN ({LICENSE_STATUSES})", name="ck_filings_license_status"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_filings_confidence_range"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_filings_effective_range",
        ),
        sa.CheckConstraint("source_url ~ '^https?://'", name="ck_filings_source_url_scheme"),
        sa.CheckConstraint(
            "raw_payload_sha256 IS NULL OR raw_payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_filings_payload_sha256",
        ),
        sa.CheckConstraint(
            r"accession_number ~ '^\d{10}-\d{2}-\d{6}$'", name="ck_filings_accession_format"
        ),
        sa.CheckConstraint(r"cik ~ '^\d{10}$'", name="ck_filings_cik_format"),
        sa.CheckConstraint("form <> ''", name="ck_filings_form_not_empty"),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name="fk_filings_entity_id_entities"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_filings_source_id_sources"),
        sa.ForeignKeyConstraint(
            ["source_tier"], ["source_tiers.tier"], name="fk_filings_source_tier_source_tiers"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_filings_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_filings"),
        sa.UniqueConstraint(
            "entity_id", "accession_number", name="uq_filings_entity_id_accession_number"
        ),
    )
    op.create_index("ix_filings_entity_id_filing_date", "filings", ["entity_id", "filing_date"])
    op.create_index("ix_filings_accession_number", "filings", ["accession_number"])
    op.execute(
        "CREATE TRIGGER filings_append_only BEFORE UPDATE OR DELETE ON filings "
        "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER filings_no_truncate BEFORE TRUNCATE ON filings "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def downgrade() -> None:
    op.drop_table("filings")
    op.drop_column("financial_facts", "source_concept")
    op.drop_column("ingestion_runs", "rows_conflicted")
