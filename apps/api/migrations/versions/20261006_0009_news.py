"""News (M0.8, ADR-018): news_items and news_mentions, both append-only.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06

news_items holds metadata and a short summary per article (never the article text: titles are
at most 500 and summaries at most 300 characters, enforced here). One row per canonical URL;
duplicate_group_id ties copies of one story together and is set at insert. news_mentions links
items to universe instruments (rule-based extraction, versioned by extractor_version).
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = (
    "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
)


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_key", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("publisher_domain", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("source_country", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("time_basis", sa.Text(), nullable=False),
        sa.Column("publisher_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duplicate_group_id", sa.Uuid(), nullable=False),
        sa.Column("data_mode", sa.Text(), nullable=False),
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
        sa.CheckConstraint("kind IN ('article', 'press_release', 'official')", name="kind"),
        sa.CheckConstraint("time_basis IN ('publisher', 'first_seen')", name="time_basis"),
        sa.CheckConstraint("data_mode IN ('live', 'fixture')", name="data_mode"),
        sa.CheckConstraint("url ~ '^https?://'", name="url_scheme"),
        sa.CheckConstraint("canonical_url ~ '^https://'", name="canonical_url_scheme"),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 500", name="title_length"),
        sa.CheckConstraint("snippet IS NULL OR length(snippet) <= 300", name="snippet_length"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_news_items_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"], ["source_tiers.tier"], name="fk_news_items_source_tier_source_tiers"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_news_items_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_news_items"),
        sa.UniqueConstraint("canonical_url", name="uq_news_items_canonical_url"),
    )
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_index("ix_news_items_duplicate_group_id", "news_items", ["duplicate_group_id"])
    op.create_index(
        "ix_news_items_source_id_published_at", "news_items", ["source_id", "published_at"]
    )

    op.create_table(
        "news_mentions",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("news_item_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("matched_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "rule IN ('exchange_ticker', 'feed_issuer', 'company_name', 'bare_ticker')",
            name="rule",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.ForeignKeyConstraint(
            ["news_item_id"], ["news_items.id"], name="fk_news_mentions_news_item_id_news_items"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_news_mentions_instrument_id_instruments",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_news_mentions"),
        sa.UniqueConstraint(
            "news_item_id",
            "instrument_id",
            "extractor_version",
            name="uq_news_mentions_news_item_id_instrument_id_extractor_version",
        ),
    )
    op.create_index("ix_news_mentions_ticker", "news_mentions", ["ticker"])

    for table in ("news_items", "news_mentions"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
        )


def downgrade() -> None:
    op.drop_table("news_mentions")
    op.drop_table("news_items")
