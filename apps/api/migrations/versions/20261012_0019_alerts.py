"""Alerts (M1.7, ADR-028): alert_rule_sets, convergence_assessments, alerts and
alert_acknowledgements, all append-only.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-12

- alert_rule_sets: one row per released rule_version of config/alert_rules.yaml, loaded by
  `make migrate` with the sha256 of its content; a changed content under a released version is
  refused (config_sync). Audited on insert.
- convergence_assessments: one company's convergence level at a time T as the database held it
  at system_time, under one alert rule version, with the whole assessment; made with the
  buyback state assignment it reads. L4 is refused: unreachable in Phase 1 (P1-4).
- alerts: a Phase 1 event (L0) or a change of a company's level, with its rule version and
  evidence; one per rule version and source. Audited on insert.
- alert_acknowledgements: acknowledging an alert, once per alert. Audited on insert.
CHECK constraints are named by suffix only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _append_only(table: str, audited: bool) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE "
        f"ON {table} FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE "
        f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )
    if audited:
        op.execute(
            f"CREATE TRIGGER {table}_audit AFTER INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
        )


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "alert_rule_sets",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("content", _jsonb(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("released", sa.Date(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(r"rule_version ~ '^\d+\.\d+\.\d+$'", name="rule_version_format"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        sa.PrimaryKeyConstraint("id", name="pk_alert_rule_sets"),
        sa.UniqueConstraint("rule_version", name="uq_alert_rule_sets_rule_version"),
    )
    _append_only("alert_rule_sets", audited=True)

    op.create_table(
        "convergence_assessments",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("buyback_assignment_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=True),
        sa.Column("assessment", _jsonb(), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("level IS NULL OR level BETWEEN 0 AND 3", name="level_phase1"),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual', 'backfill', 'replay')", name="trigger"
        ),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_convergence_assessments_instrument_id_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["alert_rule_sets.rule_version"],
            name="fk_convergence_assessments_rule_version_alert_rule_sets",
        ),
        sa.ForeignKeyConstraint(
            ["buyback_assignment_id"],
            ["buyback_state_assignments.id"],
            name="fk_convergence_assessments_buyback_assignment_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_convergence_assessments"),
        sa.UniqueConstraint(
            "instrument_id",
            "known_at",
            "rule_version",
            name="uq_convergence_assessments_instrument_known_at_rule",
        ),
    )
    op.create_index(
        "ix_convergence_assessments_rule_version_known_at",
        "convergence_assessments",
        ["rule_version", "known_at"],
    )
    _append_only("convergence_assessments", audited=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("previous_level", sa.SmallInteger(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", _jsonb(), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('event', 'level_change')", name="kind"),
        sa.CheckConstraint("level BETWEEN 0 AND 3", name="level_phase1"),
        sa.CheckConstraint(
            "previous_level IS NULL OR previous_level BETWEEN 0 AND 3", name="previous_level"
        ),
        sa.CheckConstraint("direction IS NULL OR direction IN ('up', 'down')", name="direction"),
        sa.CheckConstraint(
            "(kind = 'level_change' AND direction IS NOT NULL AND assessment_id IS NOT NULL)"
            " OR (kind = 'event' AND direction IS NULL AND level = 0)",
            name="kind_fields",
        ),
        sa.CheckConstraint("jsonb_array_length(evidence) >= 1", name="evidence_present"),
        sa.CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        sa.ForeignKeyConstraint(
            ["rule_version"],
            ["alert_rule_sets.rule_version"],
            name="fk_alerts_rule_version_alert_rule_sets",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_alerts_instrument_id_instruments"
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["convergence_assessments.id"],
            name="fk_alerts_assessment_id_convergence_assessments",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        sa.UniqueConstraint("rule_version", "source_key", name="uq_alerts_rule_version_source_key"),
    )
    op.create_index("ix_alerts_known_at", "alerts", ["known_at"])
    _append_only("alerts", audited=True)

    op.create_table(
        "alert_acknowledgements",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("note IS NULL OR length(note) <= 500", name="note_length"),
        sa.CheckConstraint("user_id = 'steven'", name="single_user"),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["alerts.id"], name="fk_alert_acknowledgements_alert_id_alerts"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alert_acknowledgements"),
        sa.UniqueConstraint("alert_id", name="uq_alert_acknowledgements_alert_id"),
    )
    _append_only("alert_acknowledgements", audited=True)


def downgrade() -> None:
    op.drop_table("alert_acknowledgements")
    op.drop_table("alerts")
    op.drop_table("convergence_assessments")
    op.drop_table("alert_rule_sets")
