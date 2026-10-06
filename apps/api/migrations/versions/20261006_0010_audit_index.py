"""Audit log index for the audit viewer (M0.9, ADR-019).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-06

The viewer filters by table and object and pages by id, newest first; this index serves both a
table filter and one object's history as the log grows. audit_log stays append-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_log_object_type_object_id_id", "audit_log", ["object_type", "object_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_object_type_object_id_id", table_name="audit_log")
