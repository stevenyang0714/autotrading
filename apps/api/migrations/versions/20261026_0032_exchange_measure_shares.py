"""Institutional flows and foreign shareholding in exchange_measures (M3.7b, ADR-040 TW23).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-26

The unit CHECK of exchange_measures gains 'shares' for the FinMind measures (net buying by
investor group, foreign and issued shares). CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "exchange_measures"


def _replace(sql: str) -> None:
    op.drop_constraint(op.f(f"ck_{TABLE}_unit"), TABLE, type_="check")
    op.create_check_constraint("unit", TABLE, sql)


def upgrade() -> None:
    _replace("unit IN ('TWD', 'percent', 'x', 'lots', 'shares')")


def downgrade() -> None:
    _replace("unit IN ('TWD', 'percent', 'x', 'lots')")
