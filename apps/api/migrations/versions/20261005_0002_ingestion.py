"""Ingestion framework: runs, raw payloads, dead letters; source rate limits; license values.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05

license_status now uses the glossary values (M0.3 plan D1):
public | licensed_personal | licensed_redistribution | restricted | unknown.
Old values on sources are mapped; financial_facts is append-only and still empty, so its
constraint is replaced without touching rows (the ADD CONSTRAINT would fail loudly otherwise).
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_LICENSES = "'public', 'licensed_personal', 'licensed_redistribution', 'restricted', 'unknown'"
OLD_LICENSES = "'public', 'terms_of_use', 'licensed', 'personal_use', 'unknown'"
AUDIT_FUNCTION_V2 = r"""
CREATE OR REPLACE FUNCTION audit_row_change() RETURNS trigger
LANGUAGE plpgsql SET timezone = 'UTC' AS $$
DECLARE
    old_doc jsonb;
    new_doc jsonb;
    changes jsonb;
    action_name text := lower(TG_OP);
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        old_doc := to_jsonb(OLD);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        new_doc := to_jsonb(NEW);
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF old_doc = new_doc THEN
            RETURN NULL;  -- nothing changed: no audit row
        END IF;
        SELECT jsonb_object_agg(n.key, jsonb_build_object('old', old_doc -> n.key, 'new', n.value))
          INTO changes
          FROM jsonb_each(new_doc) AS n
         WHERE n.value IS DISTINCT FROM old_doc -> n.key;
        IF TG_NARGS > 0 AND TG_ARGV[0] = 'fact' THEN
            action_name := 'supersede';
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        changes := old_doc;
    END IF;
    INSERT INTO audit_log (actor, action, object_type, object_id, before_hash, after_hash, details)
    VALUES (
        coalesce(nullif(current_setting('app.actor', true), ''), current_user),
        action_name,
        TG_TABLE_NAME,
        coalesce(new_doc ->> 'id', old_doc ->> 'id'),
        CASE WHEN old_doc IS NULL THEN NULL
             ELSE encode(sha256(convert_to(old_doc::text, 'UTF8')), 'hex') END,
        CASE WHEN new_doc IS NULL THEN NULL
             ELSE encode(sha256(convert_to(new_doc::text, 'UTF8')), 'hex') END,
        changes
    );
    RETURN NULL;
END $$;
"""

# 0001 body, restored on downgrade.
AUDIT_FUNCTION_V1 = r"""
CREATE OR REPLACE FUNCTION audit_row_change() RETURNS trigger
LANGUAGE plpgsql SET timezone = 'UTC' AS $$
DECLARE
    old_doc jsonb;
    new_doc jsonb;
    changes jsonb;
    action_name text := lower(TG_OP);
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        old_doc := to_jsonb(OLD);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        new_doc := to_jsonb(NEW);
    END IF;
    IF TG_OP = 'UPDATE' THEN
        SELECT jsonb_object_agg(n.key, jsonb_build_object('old', old_doc -> n.key, 'new', n.value))
          INTO changes
          FROM jsonb_each(new_doc) AS n
         WHERE n.value IS DISTINCT FROM old_doc -> n.key;
        IF TG_NARGS > 0 AND TG_ARGV[0] = 'fact' THEN
            action_name := 'supersede';
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        changes := old_doc;
    END IF;
    INSERT INTO audit_log (actor, action, object_type, object_id, before_hash, after_hash, details)
    VALUES (
        coalesce(nullif(current_setting('app.actor', true), ''), current_user),
        action_name,
        TG_TABLE_NAME,
        coalesce(new_doc ->> 'id', old_doc ->> 'id'),
        CASE WHEN old_doc IS NULL THEN NULL
             ELSE encode(sha256(convert_to(old_doc::text, 'UTF8')), 'hex') END,
        CASE WHEN new_doc IS NULL THEN NULL
             ELSE encode(sha256(convert_to(new_doc::text, 'UTF8')), 'hex') END,
        changes
    );
    RETURN NULL;
END $$;
"""

RUN_STATUSES = "'queued', 'running', 'succeeded', 'failed', 'dead_lettered', 'skipped'"


def timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    ]


def replace_license_check(table: str, values: str) -> None:
    op.drop_constraint(f"ck_{table}_license_status", table, type_="check")
    op.create_check_constraint(f"ck_{table}_license_status", table, f"license_status IN ({values})")


def upgrade() -> None:
    # ---- license values (glossary) ----
    op.execute(
        "UPDATE sources SET license_status = CASE license_status "
        "WHEN 'terms_of_use' THEN 'restricted' WHEN 'licensed' THEN 'licensed_personal' "
        "WHEN 'personal_use' THEN 'licensed_personal' ELSE license_status END"
    )
    replace_license_check("sources", NEW_LICENSES)
    replace_license_check("financial_facts", NEW_LICENSES)

    # ---- per-source token bucket ----
    op.add_column(
        "sources",
        sa.Column(
            "rate_limit_per_second",
            sa.Numeric(8, 3),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "sources",
        sa.Column("rate_limit_burst", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint(
        "ck_sources_rate_limit_positive", "sources", "rate_limit_per_second > 0"
    )
    op.create_check_constraint(
        "ck_sources_rate_limit_burst_positive", "sources", "rate_limit_burst >= 1"
    )

    # Unchanged UPDATEs (e.g. re-syncing config/sources.yaml) no longer write audit rows.
    op.execute(AUDIT_FUNCTION_V2)

    op.execute(
        """
        CREATE FUNCTION forbid_row_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'append-only table %: % is not allowed', TG_TABLE_NAME, TG_OP;
        END $$;
        """
    )

    # ---- ingestion runs ----
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("job", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_inserted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_unchanged", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "raw_payload_keys",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("job ~ '^[a-z][a-z0-9_.]*$'", name="ck_ingestion_runs_job_format"),
        sa.CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{64}$'", name="ck_ingestion_runs_idempotency_key_format"
        ),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="ck_ingestion_runs_status"),
        sa.CheckConstraint("attempt >= 1", name="ck_ingestion_runs_attempt_positive"),
        sa.CheckConstraint(
            "window_end IS NULL OR window_start IS NULL OR window_end >= window_start",
            name="ck_ingestion_runs_window_order",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_ingestion_runs_source_id_sources"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_runs"),
    )
    op.create_index(
        "uq_ingestion_runs_succeeded_key",
        "ingestion_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.create_index(
        "ix_ingestion_runs_source_id_created_at", "ingestion_runs", ["source_id", "created_at"]
    )
    op.execute(
        "CREATE TRIGGER ingestion_runs_touch BEFORE UPDATE ON ingestion_runs FOR EACH ROW "
        "WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION touch_mutable_row()"
    )
    op.create_foreign_key(
        "fk_financial_facts_ingestion_run_id_ingestion_runs",
        "financial_facts",
        "ingestion_runs",
        ["ingestion_run_id"],
        ["id"],
    )

    # ---- raw payloads (append-only) ----
    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_payloads_sha256_format"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_raw_payloads_size_non_negative"),
        sa.CheckConstraint("source_url ~ '^https?://'", name="ck_raw_payloads_source_url_scheme"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_raw_payloads_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_raw_payloads_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_payloads"),
        sa.UniqueConstraint("source_id", "sha256", name="uq_raw_payloads_source_id_sha256"),
        sa.UniqueConstraint("object_key", name="uq_raw_payloads_object_key"),
    )
    op.execute(
        "CREATE TRIGGER raw_payloads_append_only BEFORE UPDATE OR DELETE ON raw_payloads "
        "FOR EACH ROW EXECUTE FUNCTION forbid_row_change()"
    )
    op.execute(
        "CREATE TRIGGER raw_payloads_no_truncate BEFORE TRUNCATE ON raw_payloads "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )

    # ---- dead letters (resolvable, audited) ----
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("job", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "failed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("attempts >= 1", name="ck_dead_letters_attempts_positive"),
        sa.CheckConstraint(
            "(resolved_at IS NULL) = (resolution IS NULL)",
            name="ck_dead_letters_resolution_complete",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_dead_letters_ingestion_run_id_ingestion_runs",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_dead_letters_source_id_sources"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dead_letters"),
        sa.UniqueConstraint("ingestion_run_id", name="uq_dead_letters_ingestion_run_id"),
    )
    op.execute(
        "CREATE TRIGGER dead_letters_touch BEFORE UPDATE ON dead_letters FOR EACH ROW "
        "WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION touch_mutable_row()"
    )
    op.execute(
        "CREATE TRIGGER dead_letters_audit AFTER INSERT OR UPDATE OR DELETE ON dead_letters "
        "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
    )


def downgrade() -> None:
    op.drop_table("dead_letters")
    op.drop_table("raw_payloads")
    op.drop_constraint(
        "fk_financial_facts_ingestion_run_id_ingestion_runs", "financial_facts", type_="foreignkey"
    )
    op.drop_table("ingestion_runs")
    op.execute("DROP FUNCTION forbid_row_change()")
    op.drop_constraint("ck_sources_rate_limit_burst_positive", "sources", type_="check")
    op.drop_constraint("ck_sources_rate_limit_positive", "sources", type_="check")
    op.drop_column("sources", "rate_limit_burst")
    op.drop_column("sources", "rate_limit_per_second")
    op.execute(
        "UPDATE sources SET license_status = CASE license_status "
        "WHEN 'restricted' THEN 'terms_of_use' WHEN 'licensed_personal' THEN 'personal_use' "
        "WHEN 'licensed_redistribution' THEN 'licensed' ELSE license_status END"
    )
    replace_license_check("sources", OLD_LICENSES)
    replace_license_check("financial_facts", OLD_LICENSES)
    op.execute(AUDIT_FUNCTION_V1)
