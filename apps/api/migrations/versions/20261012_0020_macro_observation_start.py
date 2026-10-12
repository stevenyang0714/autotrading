"""macro_series.observation_start (M2.1, ADR-029): the earliest observation a series' daily
run reads.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-12

NFCI, NFCICREDIT and STLFSI4 re-estimate their whole history every week, so every vintage
changes almost every value: read from 1971 that is over a million rows a day. These series
are read from 2015 (`config/macro_series.yaml`); NULL reads the full history as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("macro_series", sa.Column("observation_start", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("macro_series", "observation_start")
