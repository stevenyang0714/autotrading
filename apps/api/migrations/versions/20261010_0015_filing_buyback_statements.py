"""Buyback announcements from 8-Ks (M1.4a, ADR-025 B1): filing_buyback_statements, append-only.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-10

One row per repurchase authorization, plan or remaining amount a sentence of an 8-K document
states, as read by `sec.eight_k` with one extractor version. Only the sentence (at most 300
characters) is kept, never the document. published_at is the filing's acceptance time.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)
TABLE = "filing_buyback_statements"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("accession_number", sa.Text(), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("remaining_amount", sa.Numeric(), nullable=True),
        sa.Column("stated_date", sa.Date(), nullable=True),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
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
        sa.CheckConstraint(r"accession_number ~ '^\d{10}-\d{2}-\d{6}$'", name="accession_format"),
        sa.CheckConstraint("kind IN ('new', 'increase', 'plan', 'remaining')", name="kind"),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.CheckConstraint(
            "remaining_amount IS NULL OR remaining_amount > 0", name="remaining_positive"
        ),
        sa.CheckConstraint("length(sentence) BETWEEN 1 AND 300", name="sentence_length"),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name="fk_filing_buyback_statements_entity_id_entities"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_filing_buyback_statements_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"],
            ["source_tiers.tier"],
            name="fk_filing_buyback_statements_source_tier_source_tiers",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_filing_buyback_statements_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_filing_buyback_statements"),
        sa.UniqueConstraint(
            "entity_id",
            "source_url",
            "sentence",
            "extractor_version",
            name="uq_filing_buyback_statements_source_sentence",
        ),
    )
    op.create_index(
        "ix_filing_buyback_statements_entity_id_published_at",
        TABLE,
        ["entity_id", "published_at"],
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_no_truncate BEFORE TRUNCATE ON {TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def downgrade() -> None:
    op.drop_table(TABLE)
