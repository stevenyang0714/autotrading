"""Data-quality notes on ingestion runs (ADR-013 amendment, 2026-10-06).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06

A job can record what it noticed or corrected about its source, e.g. `sec.company` moving SEC's
acceptance times back by the Eastern offset after checking the filing headers. The notes are
shown with the run on Data Health.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "notes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_runs", "notes")
