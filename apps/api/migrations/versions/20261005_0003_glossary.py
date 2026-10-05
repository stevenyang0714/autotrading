"""Glossary registry: immutable versions of complete glossary terms (02 §22, M0.4).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT_FIELDS = (
    "display_name",
    "category",
    "short_definition",
    "full_definition",
    "formula",
    "unit",
    "example",
    "direction",
    "interpretation",
    "why_it_matters",
    "source",
    "source_url",
    "as_of",
    "update_cadence",
    "caveats",
)


def upgrade() -> None:
    op.create_table(
        "glossary_terms",
        sa.Column("term_id", sa.Text(), nullable=False),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        *(sa.Column(name, sa.Text(), nullable=False) for name in TEXT_FIELDS),
        sa.Column("related_terms", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "term_id ~ '^[a-z][a-z0-9_]*$'", name="ck_glossary_terms_term_id_format"
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_glossary_terms_content_sha256_format"
        ),
        sa.CheckConstraint("source_url ~ '^https?://'", name="ck_glossary_terms_source_url_scheme"),
        sa.PrimaryKeyConstraint("term_id", "methodology_version", name="pk_glossary_terms"),
    )
    op.execute(
        "CREATE TRIGGER glossary_terms_append_only BEFORE UPDATE OR DELETE ON glossary_terms "
        "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER glossary_terms_no_truncate BEFORE TRUNCATE ON glossary_terms "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )


def downgrade() -> None:
    op.drop_table("glossary_terms")
