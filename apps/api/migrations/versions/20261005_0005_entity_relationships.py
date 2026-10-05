"""Entity relationships (M0.5b, ADR-014): successor issuers such as a new holding company.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05

Mutable and audited like identifiers: rows come from config/universe.yaml (`predecessors:`)
through the sec.tickers job, with an SEC filing as evidence.

CHECK constraints are named by their suffix only: the metadata naming convention adds the
`ck_<table>_` prefix (passing the full name, as 0001-0004 did, doubles it).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_relationships",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("predecessor_entity_id", sa.Uuid(), nullable=False),
        sa.Column("successor_entity_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_url", sa.Text(), nullable=False),
        sa.Column("evidence_accession", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "relationship_type IN ('successor_issuer')",
            name="relationship_type",
        ),
        sa.CheckConstraint(
            "predecessor_entity_id <> successor_entity_id",
            name="distinct_entities",
        ),
        sa.CheckConstraint("evidence_url ~ '^https?://'", name="evidence_url_scheme"),
        sa.CheckConstraint(
            r"evidence_accession IS NULL OR evidence_accession ~ '^\d{10}-\d{2}-\d{6}$'",
            name="evidence_accession_format",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_entity_id"],
            ["entities.id"],
            name="fk_entity_relationships_predecessor_entity_id_entities",
        ),
        sa.ForeignKeyConstraint(
            ["successor_entity_id"],
            ["entities.id"],
            name="fk_entity_relationships_successor_entity_id_entities",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_entity_relationships_source_id_sources"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_relationships"),
        sa.UniqueConstraint(
            "predecessor_entity_id",
            "successor_entity_id",
            "relationship_type",
            name="uq_entity_relationships_pair_type",
        ),
    )
    op.execute(
        "CREATE TRIGGER entity_relationships_touch BEFORE UPDATE ON entity_relationships "
        "FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION touch_mutable_row()"
    )
    op.execute(
        "CREATE TRIGGER entity_relationships_audit AFTER INSERT OR UPDATE OR DELETE "
        "ON entity_relationships FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )


def downgrade() -> None:
    op.drop_table("entity_relationships")
