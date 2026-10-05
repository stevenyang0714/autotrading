"""Baseline: canonical registries, source registry, identifiers, bitemporal facts, audit log.

Revision ID: 0001
Revises:
Create Date: 2026-10-05

Seed rows are literals on purpose: a migration is a frozen snapshot and must not import app
code. tests/integration/test_schema.py asserts they equal autotrading.domain.registries.

Triggers are guardrails, not security: the app role is a superuser and could disable them.
A future migration that must bypass one has to say why in an ADR (CLAUDE.md, ADR-007).
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LICENSE_STATUSES = "'public', 'terms_of_use', 'licensed', 'personal_use', 'unknown'"

SIGNAL_FAMILIES = [
    (1, "Macro Regime"),
    (2, "Corporate Actions & Capital Structure"),
    (3, "Fundamental & Valuation"),
    (4, "Earnings & Estimates"),
    (5, "Price / Trend / Factor"),
    (6, "Options & Volatility"),
    (7, "Positioning & Flows"),
    (8, "Alternative / Physical / Supply Chain"),
    (9, "Geopolitical / Policy / Social Intelligence"),
    (10, "Tail Risk / Regime Stress"),
]

# 02 §18 wording (errata E14).
STRATEGIES = [
    (
        "S1",
        "Buyback + Value + Quality",
        "paper_semi_auto",
        "OOS + walk-forward + robustness + risk",
    ),
    (
        "S2",
        "Earnings Surprise + Revisions + Momentum",
        "paper_semi_auto",
        "OOS + event timing + cost",
    ),
    ("S3", "Macro Regime / ETF Rotation", "paper_semi_auto", "regime robustness"),
    ("S4", "Medium-term Momentum", "paper_semi_auto", "factor overlap + OOS"),
    ("S5", "Event / Supply-chain", "alert_semi_auto", "causal evidence + market confirmation"),
    ("S6", "Options / Volatility", "alert_semi_auto", "Greeks + liquidity + max loss"),
    ("S7", "Corporate Insider", "alert", "source/context validation"),
    ("S8", "Congress PTR", "alert", "disclosure-lag aware"),
    ("S9", "Political / Trump headlines", "alert", "official status + transmission map"),
    ("S10", "Intraday social headline", "alert_only", "no social-only execution"),
    ("S11", "Small-cap squeeze", "alert_only", "no default auto"),
    ("S12", "0DTE speculation", "alert_only", "no default auto"),
]

# 01 §20, labels from 01 §7 (errata E2: Tier 1 = strongest).
SOURCE_TIERS = [
    (
        1,
        "Primary / official",
        "trade-critical confirmation",
        "SEC/EDGAR; licensed market-price/venue feeds (e.g., Massive); issuer filings; "
        "FRED/ALFRED; Treasury; CFTC; White House; House/Senate disclosure; official agency data",
    ),
    (
        2,
        "Professional media",
        "fast discovery/context; license required",
        "Reuters; FT; WSJ; Bloomberg; AP; CNBC; Economist; licensed research/data",
    ),
    (
        3,
        "Specialist / social",
        "early signal / attention",
        "X research accounts; specialist blogs/newsletters; community",
    ),
    (
        4,
        "Anonymous / unverified",
        "weak lead only; never sole execution evidence",
        "anonymous source; repost; unverified social",
    ),
]

REGISTRY_TABLES = ("signal_families", "strategies", "source_tiers")
MUTABLE_TABLES = ("sources", "entities", "instruments", "identifiers")
FACT_TABLES = ("financial_facts",)
FACT_KEY = ("entity_id", "metric_id", "unit", "period_start", "period_end")

FUNCTIONS_SQL = r"""
CREATE FUNCTION forbid_registry_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'canonical registry % is immutable (CLAUDE.md; change requires an ADR)',
        TG_TABLE_NAME USING ERRCODE = 'raise_exception';
END $$;

CREATE FUNCTION forbid_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'TRUNCATE is not allowed on append-only table %', TG_TABLE_NAME;
END $$;

CREATE FUNCTION touch_mutable_row() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.created_at := OLD.created_at;
    NEW.updated_at := now();
    NEW.version := OLD.version + 1;
    RETURN NEW;
END $$;

-- System time comes from the database clock only (ADR-012).
CREATE FUNCTION fact_before_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.recorded_at := now();
    NEW.superseded_at := NULL;
    RETURN NEW;
END $$;

-- Append-only facts (ADR-007): no DELETE; the only UPDATE sets superseded_at once.
CREATE FUNCTION fact_before_update_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'append-only fact table %: DELETE is not allowed', TG_TABLE_NAME;
    END IF;
    IF OLD.superseded_at IS NOT NULL THEN
        RAISE EXCEPTION 'append-only fact table %: row % is already superseded',
            TG_TABLE_NAME, OLD.id;
    END IF;
    IF NEW.superseded_at IS NULL THEN
        RAISE EXCEPTION 'append-only fact table %: the only allowed update sets superseded_at',
            TG_TABLE_NAME;
    END IF;
    IF (to_jsonb(NEW) - 'superseded_at') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION 'append-only fact table %: only superseded_at may change', TG_TABLE_NAME;
    END IF;
    NEW.superseded_at := now();
    RETURN NEW;
END $$;

-- Row JSON is rendered in UTC so the same row always hashes the same way.
CREATE FUNCTION audit_row_change() RETURNS trigger LANGUAGE plpgsql SET timezone = 'UTC' AS $$
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

CREATE FUNCTION forbid_audit_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END $$;
"""

DROP_FUNCTIONS = (
    "audit_row_change",
    "forbid_audit_change",
    "fact_before_update_delete",
    "fact_before_insert",
    "touch_mutable_row",
    "forbid_truncate",
    "forbid_registry_change",
)


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


def upgrade() -> None:
    # The timescale image pre-installs the extension in the default database; IF NOT EXISTS
    # keeps this idempotent there and still installs it in an empty database.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(FUNCTIONS_SQL)

    # ---- canonical registries ----
    op.create_table(
        "signal_families",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("id BETWEEN 1 AND 10", name="ck_signal_families_id_range"),
        sa.PrimaryKeyConstraint("id", name="pk_signal_families"),
        sa.UniqueConstraint("name", name="uq_signal_families_name"),
    )
    op.create_table(
        "strategies",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("default_mode", sa.Text(), nullable=False),
        sa.Column("unlock_condition", sa.Text(), nullable=False),
        sa.CheckConstraint("id ~ '^S([1-9]|1[0-2])$'", name="ck_strategies_id_format"),
        sa.CheckConstraint(
            "default_mode IN ('paper_semi_auto', 'alert_semi_auto', 'alert', 'alert_only')",
            name="ck_strategies_default_mode",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategies"),
        sa.UniqueConstraint("name", name="uq_strategies_name"),
    )
    op.create_table(
        "source_tiers",
        sa.Column("tier", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("examples", sa.Text(), nullable=False),
        sa.CheckConstraint("tier BETWEEN 1 AND 4", name="ck_source_tiers_tier_range"),
        sa.PrimaryKeyConstraint("tier", name="pk_source_tiers"),
        sa.UniqueConstraint("label", name="uq_source_tiers_label"),
    )
    families = sa.table("signal_families", sa.column("id"), sa.column("name"))
    op.bulk_insert(families, [{"id": i, "name": n} for i, n in SIGNAL_FAMILIES])
    strategies = sa.table(
        "strategies",
        sa.column("id"),
        sa.column("name"),
        sa.column("default_mode"),
        sa.column("unlock_condition"),
    )
    op.bulk_insert(
        strategies,
        [
            {"id": i, "name": n, "default_mode": m, "unlock_condition": u}
            for i, n, m, u in STRATEGIES
        ],
    )
    tiers = sa.table(
        "source_tiers",
        sa.column("tier"),
        sa.column("label"),
        sa.column("role"),
        sa.column("examples"),
    )
    op.bulk_insert(
        tiers, [{"tier": t, "label": lb, "role": r, "examples": e} for t, lb, r, e in SOURCE_TIERS]
    )
    for table in REGISTRY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable "
            f"BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_registry_change()"
        )

    # ---- reference data ----
    op.create_table(
        "sources",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("license_status", sa.Text(), nullable=False),
        sa.Column(
            "access_status", sa.Text(), server_default=sa.text("'pending_review'"), nullable=False
        ),
        sa.Column("update_cadence", sa.Text(), nullable=False),
        sa.Column("freshness_sla_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "topics", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        *timestamps(),
        sa.CheckConstraint("id ~ '^[a-z][a-z0-9_]*$'", name="ck_sources_id_format"),
        sa.CheckConstraint(
            f"license_status IN ({LICENSE_STATUSES})", name="ck_sources_license_status"
        ),
        sa.CheckConstraint(
            "access_status IN ('active', 'no_credentials', 'disabled', 'pending_review')",
            name="ck_sources_access_status",
        ),
        sa.CheckConstraint(
            "update_cadence IN ('intraday', 'daily', 'weekly', 'monthly', 'per_filing', "
            "'per_release')",
            name="ck_sources_update_cadence",
        ),
        sa.CheckConstraint("freshness_sla_seconds > 0", name="ck_sources_freshness_sla_positive"),
        sa.ForeignKeyConstraint(
            ["tier"], ["source_tiers.tier"], name="fk_sources_tier_source_tiers"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
    )
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "entity_type IN ('company', 'fund', 'government', 'other')",
            name="ck_entities_entity_type",
        ),
        sa.CheckConstraint(
            "country IS NULL OR country ~ '^[A-Z]{2}$'", name="ck_entities_country_format"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entities"),
    )
    op.create_table(
        "instruments",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("instrument_type", sa.Text(), nullable=False),
        sa.Column("primary_exchange", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "instrument_type IN ('equity', 'etf', 'index', 'future', 'option', 'fx', 'other')",
            name="ck_instruments_instrument_type",
        ),
        sa.CheckConstraint(
            "primary_exchange IS NULL OR primary_exchange ~ '^[A-Z0-9]{4}$'",
            name="ck_instruments_mic_format",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_instruments_currency_format"),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name="fk_instruments_entity_id_entities"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_instruments"),
    )
    op.create_table(
        "identifiers",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("id_type", sa.Text(), nullable=False),
        sa.Column("id_namespace", sa.Text(), nullable=False),
        sa.Column("id_value", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "num_nonnulls(entity_id, instrument_id) = 1", name="ck_identifiers_one_subject"
        ),
        sa.CheckConstraint(
            "id_type IN ('ticker', 'cik', 'figi', 'composite_figi', 'share_class_figi')",
            name="ck_identifiers_id_type",
        ),
        sa.CheckConstraint(
            "id_namespace ~ '^[a-z][a-z0-9_]*$'", name="ck_identifiers_namespace_format"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="ck_identifiers_valid_range"
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name="fk_identifiers_entity_id_entities"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_identifiers_instrument_id_instruments"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_identifiers_source_id_sources"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identifiers"),
    )
    # NULL valid_to means "no end"; '[)' makes consecutive periods touch without overlapping.
    op.execute(
        "ALTER TABLE identifiers ADD CONSTRAINT ex_identifiers_value_period EXCLUDE USING gist ("
        "id_type WITH =, id_namespace WITH =, id_value WITH =, "
        "tstzrange(valid_from, valid_to, '[)') WITH &&)"
    )
    op.execute(
        "ALTER TABLE identifiers ADD CONSTRAINT ex_identifiers_subject_period EXCLUDE USING gist ("
        "(coalesce(entity_id, instrument_id)) WITH =, id_type WITH =, id_namespace WITH =, "
        "tstzrange(valid_from, valid_to, '[)') WITH &&)"
    )

    # ---- facts ----
    op.create_table(
        "financial_facts",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("metric_id", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("fiscal_period", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accession_id", sa.Text(), nullable=True),
        sa.Column("vintage", sa.Text(), nullable=True),
        sa.Column("restated_flag", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supersedes_fact_id", sa.Uuid(), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        # provenance
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
        # system time
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "published_at_precision IN ('exact', 'day')", name="ck_financial_facts_precision"
        ),
        sa.CheckConstraint(
            f"license_status IN ({LICENSE_STATUSES})", name="ck_financial_facts_license_status"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_financial_facts_confidence_range"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_financial_facts_effective_range",
        ),
        sa.CheckConstraint(
            "source_url ~ '^https?://'", name="ck_financial_facts_source_url_scheme"
        ),
        sa.CheckConstraint(
            "raw_payload_sha256 IS NULL OR raw_payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_financial_facts_payload_sha256",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= recorded_at",
            name="ck_financial_facts_system_time_order",
        ),
        sa.CheckConstraint("version >= 1", name="ck_financial_facts_version_positive"),
        sa.CheckConstraint(
            "metric_id ~ '^[a-z][a-z0-9_]*$'", name="ck_financial_facts_metric_id_format"
        ),
        sa.CheckConstraint(
            "value NOT IN ('NaN', 'Infinity', '-Infinity')", name="ck_financial_facts_value_finite"
        ),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="ck_financial_facts_currency_format"
        ),
        sa.CheckConstraint(
            "period_start IS NULL OR period_start <= period_end",
            name="ck_financial_facts_period_order",
        ),
        sa.CheckConstraint(
            "revision_reason IS NULL OR revision_reason IN ('restatement', 'revision', "
            "'correction')",
            name="ck_financial_facts_revision_reason",
        ),
        sa.CheckConstraint(
            "(supersedes_fact_id IS NULL) = (revision_reason IS NULL)",
            name="ck_financial_facts_revision_link",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name="fk_financial_facts_entity_id_entities"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_fact_id"],
            ["financial_facts.id"],
            name="fk_financial_facts_supersedes_fact_id_financial_facts",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_financial_facts_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["source_tier"],
            ["source_tiers.tier"],
            name="fk_financial_facts_source_tier_source_tiers",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_facts"),
    )
    op.create_index(
        "uq_financial_facts_key_version",
        "financial_facts",
        [*FACT_KEY, "version"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_financial_facts_current_key_published",
        "financial_facts",
        [*FACT_KEY, "published_at"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    # ---- audit ----
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("before_hash", sa.Text(), nullable=True),
        sa.Column("after_hash", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "action IN ('insert', 'update', 'delete', 'supersede')", name="ck_audit_log_action"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.execute(
        "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION forbid_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
    )

    # ---- triggers on mutable and fact tables ----
    for table in MUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_touch BEFORE UPDATE ON {table} FOR EACH ROW "
            "WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION touch_mutable_row()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_audit AFTER INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION audit_row_change()"
        )
    for table in FACT_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_system_time BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION fact_before_insert()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION fact_before_update_delete()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_audit AFTER UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION audit_row_change('fact')"
        )


def downgrade() -> None:
    # Dropping the tables drops their triggers. Extensions stay: the image pre-installs
    # timescaledb, and other databases on the server may rely on btree_gist.
    for table in (
        "audit_log",
        "financial_facts",
        "identifiers",
        "instruments",
        "entities",
        "sources",
        "source_tiers",
        "strategies",
        "signal_families",
    ):
        op.drop_table(table)
    for function in DROP_FUNCTIONS:
        op.execute(f"DROP FUNCTION {function}()")
