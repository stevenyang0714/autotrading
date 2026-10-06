"""ORM models. Keep in step with the migrations; `alembic check` fails on drift.

Triggers, exclusion constraints and seed rows live only in the migrations
(see migrations/versions/20261005_0001_baseline.py); tests assert they exist.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autotrading.db.base import Base
from autotrading.db.mixins import (
    LICENSE_STATUSES,
    FactMixin,
    MutableRowMixin,
    ProvenanceMixin,
    bitemporal_constraints,
    provenance_constraints,
    sql_in,
)

DEFAULT_MODES = ("paper_semi_auto", "alert_semi_auto", "alert", "alert_only")
ACCESS_STATUSES = ("active", "no_credentials", "disabled", "pending_review")
UPDATE_CADENCES = ("intraday", "daily", "weekly", "monthly", "per_filing", "per_release")
ENTITY_TYPES = ("company", "fund", "government", "other")
INSTRUMENT_TYPES = ("equity", "etf", "index", "future", "option", "fx", "other")
ID_TYPES = ("ticker", "cik", "figi", "composite_figi", "share_class_figi")
RELATIONSHIP_TYPES = ("successor_issuer",)
FREQUENCIES = ("D", "W", "BW", "M", "Q", "SA", "A")
FEED_STATUSES = (
    "live_consolidated",
    "live_single_venue",
    "delayed",
    "end_of_day",
    "stale",
    "unavailable",
    "fixture",
    "demo",
)
BAR_FEED_STATUSES = ("end_of_day", "fixture")  # daily bars are closes, never live
ADJUSTMENTS = ("raw", "split")
REVISION_REASONS = ("restatement", "revision", "correction")
AUDIT_ACTIONS = ("insert", "update", "delete", "supersede")
RUN_STATUSES = ("queued", "running", "succeeded", "failed", "dead_lettered", "skipped")


# ---------- canonical registries (seeded by migration, immutable) ----------


class SignalFamilyRow(Base):
    __tablename__ = "signal_families"
    __table_args__ = (CheckConstraint("id BETWEEN 1 AND 10", name="id_range"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, unique=True)


class StrategyRow(Base):
    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint("id ~ '^S([1-9]|1[0-2])$'", name="id_format"),
        CheckConstraint(sql_in("default_mode", DEFAULT_MODES), name="default_mode"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    default_mode: Mapped[str] = mapped_column(Text)
    unlock_condition: Mapped[str] = mapped_column(Text)


class SourceTierRow(Base):
    __tablename__ = "source_tiers"
    __table_args__ = (CheckConstraint("tier BETWEEN 1 AND 4", name="tier_range"),)

    tier: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[str] = mapped_column(Text)
    examples: Mapped[str] = mapped_column(Text)


# ---------- reference data (mutable, audited) ----------


class Source(MutableRowMixin, Base):
    """Source Registry entry (02 §4, M0.2). Rows are loaded from config/sources.yaml in M0.3."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("id ~ '^[a-z][a-z0-9_]*$'", name="id_format"),
        CheckConstraint(sql_in("license_status", LICENSE_STATUSES), name="license_status"),
        CheckConstraint(sql_in("access_status", ACCESS_STATUSES), name="access_status"),
        CheckConstraint(sql_in("update_cadence", UPDATE_CADENCES), name="update_cadence"),
        CheckConstraint("freshness_sla_seconds > 0", name="freshness_sla_positive"),
        CheckConstraint("rate_limit_per_second > 0", name="rate_limit_positive"),
        CheckConstraint("rate_limit_burst >= 1", name="rate_limit_burst_positive"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    tier: Mapped[int] = mapped_column(SmallInteger, ForeignKey("source_tiers.tier"))
    license_status: Mapped[str] = mapped_column(Text)
    access_status: Mapped[str] = mapped_column(Text, server_default=text("'pending_review'"))
    update_cadence: Mapped[str] = mapped_column(Text)
    freshness_sla_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("100"))
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # Token bucket per source (M0.3): sustained requests per second and burst size.
    rate_limit_per_second: Mapped[Decimal] = mapped_column(Numeric(8, 3), server_default=text("1"))
    rate_limit_burst: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class Entity(MutableRowMixin, Base):
    """Issuer or other legal entity."""

    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint(sql_in("entity_type", ENTITY_TYPES), name="entity_type"),
        CheckConstraint("country IS NULL OR country ~ '^[A-Z]{2}$'", name="country_format"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)


class Instrument(MutableRowMixin, Base):
    __tablename__ = "instruments"
    __table_args__ = (
        CheckConstraint(sql_in("instrument_type", INSTRUMENT_TYPES), name="instrument_type"),
        CheckConstraint(
            "primary_exchange IS NULL OR primary_exchange ~ '^[A-Z0-9]{4}$'", name="mic_format"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("entities.id"))
    instrument_type: Mapped[str] = mapped_column(Text)
    primary_exchange: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Identifier(MutableRowMixin, Base):
    """Ticker / CIK / FIGI with a validity period.

    The migration adds two exclusion constraints: one identifier value maps to one subject at a
    time, and one subject has one value per (id_type, id_namespace) at a time. The namespace
    keeps provider conventions apart (SEC "BRK-B" vs Alpaca "BRK.B").
    """

    __tablename__ = "identifiers"
    __table_args__ = (
        CheckConstraint("num_nonnulls(entity_id, instrument_id) = 1", name="one_subject"),
        CheckConstraint(sql_in("id_type", ID_TYPES), name="id_type"),
        CheckConstraint("id_namespace ~ '^[a-z][a-z0-9_]*$'", name="namespace_format"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_range"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("entities.id"))
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("instruments.id"))
    id_type: Mapped[str] = mapped_column(Text)
    id_namespace: Mapped[str] = mapped_column(Text)
    id_value: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id"))


class EntityRelationship(MutableRowMixin, Base):
    """A link between two entities, e.g. a holding company that succeeded an issuer (ADR-014).

    Curated from config/universe.yaml with an SEC filing as evidence; audited like identifiers.
    effective_at is when the successor took over (e.g. the 8-K12B acceptance time).
    """

    __tablename__ = "entity_relationships"
    __table_args__ = (
        CheckConstraint(sql_in("relationship_type", RELATIONSHIP_TYPES), name="relationship_type"),
        CheckConstraint("predecessor_entity_id <> successor_entity_id", name="distinct_entities"),
        CheckConstraint("evidence_url ~ '^https?://'", name="evidence_url_scheme"),
        CheckConstraint(
            r"evidence_accession IS NULL OR evidence_accession ~ '^\d{10}-\d{2}-\d{6}$'",
            name="evidence_accession_format",
        ),
        UniqueConstraint(
            "predecessor_entity_id",
            "successor_entity_id",
            "relationship_type",
            name="uq_entity_relationships_pair_type",
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    predecessor_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id"))
    successor_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id"))
    relationship_type: Mapped[str] = mapped_column(Text)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_url: Mapped[str] = mapped_column(Text)
    evidence_accession: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id"))


# ---------- ingestion (M0.3) ----------


class IngestionRun(MutableRowMixin, Base):
    """One ingestion job execution; retries of the same message update the same row.

    The idempotency key is sha256(source, job, canonical params, window). A key can succeed
    only once (partial unique index), so re-running a finished job is recorded as `skipped`.
    """

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("job ~ '^[a-z][a-z0-9_.]*$'", name="job_format"),
        CheckConstraint("idempotency_key ~ '^[0-9a-f]{64}$'", name="idempotency_key_format"),
        CheckConstraint(sql_in("status", RUN_STATUSES), name="status"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint(
            "window_end IS NULL OR window_start IS NULL OR window_end >= window_start",
            name="window_order",
        ),
        Index(
            "uq_ingestion_runs_succeeded_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
        Index("ix_ingestion_runs_source_id_created_at", "source_id", "created_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id"))
    job: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_inserted: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rows_unchanged: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Values not stored because they contradict a stored value of the same publication (M0.5).
    rows_conflicted: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    raw_payload_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    error_class: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class RawPayload(Base):
    """Metadata of a raw provider response stored in the object store (append-only).

    Content-addressed: one row per (source, sha256), however many runs fetched it.
    """

    __tablename__ = "raw_payloads"
    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("source_url ~ '^https?://'", name="source_url_scheme"),
        UniqueConstraint("source_id", "sha256", name="uq_raw_payloads_source_id_sha256"),
        UniqueConstraint("object_key", name="uq_raw_payloads_object_key"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id"))
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ingestion_runs.id"))
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeadLetter(MutableRowMixin, Base):
    """A job that still failed after its last retry. Resolving it is an audited update."""

    __tablename__ = "dead_letters"
    __table_args__ = (
        CheckConstraint("attempts >= 1", name="attempts_positive"),
        CheckConstraint("(resolved_at IS NULL) = (resolution IS NULL)", name="resolution_complete"),
        UniqueConstraint("ingestion_run_id", name="uq_dead_letters_ingestion_run_id"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ingestion_runs.id"))
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id"))
    job: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    idempotency_key: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    error_class: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text)


# ---------- glossary registry (M0.4, append-only) ----------


class GlossaryTermRow(Base):
    """One immutable version of a complete glossary term (02 §22).

    Loaded from docs/glossary/glossary_seed.yaml by `make migrate`; only `complete` terms are
    registered. Changing a term's content requires a new methodology_version.
    """

    __tablename__ = "glossary_terms"
    __table_args__ = (
        CheckConstraint("term_id ~ '^[a-z][a-z0-9_]*$'", name="term_id_format"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint("source_url ~ '^https?://'", name="source_url_scheme"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    term_id: Mapped[str] = mapped_column(Text, primary_key=True)
    methodology_version: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    short_definition: Mapped[str] = mapped_column(Text)
    full_definition: Mapped[str] = mapped_column(Text)
    formula: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    example: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    interpretation: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    as_of: Mapped[str] = mapped_column(Text)
    update_cadence: Mapped[str] = mapped_column(Text)
    caveats: Mapped[str] = mapped_column(Text)
    related_terms: Mapped[list[str]] = mapped_column(ARRAY(Text))
    content_sha256: Mapped[str] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- facts (append-only, bitemporal) ----------


class FinancialFact(FactMixin, Base):
    """FinancialFact (02 §28, errata E1). Written from M0.5 by the SEC adapter."""

    __tablename__ = "financial_facts"
    __fact_key__ = ("entity_id", "metric_id", "unit", "period_start", "period_end")
    __table_args__ = (
        *provenance_constraints(),
        *bitemporal_constraints(),
        CheckConstraint("metric_id ~ '^[a-z][a-z0-9_]*$'", name="metric_id_format"),
        CheckConstraint("value NOT IN ('NaN', 'Infinity', '-Infinity')", name="value_finite"),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("period_start IS NULL OR period_start <= period_end", name="period_order"),
        CheckConstraint(
            "revision_reason IS NULL OR " + sql_in("revision_reason", REVISION_REASONS),
            name="revision_reason",
        ),
        CheckConstraint(
            "(supersedes_fact_id IS NULL) = (revision_reason IS NULL)", name="revision_link"
        ),
        Index(
            "uq_financial_facts_key_version",
            *__fact_key__,
            "version",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        # One current version per fact key and publication time; also the idempotency key.
        Index(
            "uq_financial_facts_current_key_published",
            *__fact_key__,
            "published_at",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id"))
    metric_id: Mapped[str] = mapped_column(Text)
    value: Mapped[Decimal] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(Text)
    fiscal_period: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accession_id: Mapped[str | None] = mapped_column(Text)
    vintage: Mapped[str | None] = mapped_column(Text)
    restated_flag: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    supersedes_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("financial_facts.id")
    )
    revision_reason: Mapped[str | None] = mapped_column(Text)
    # Raw XBRL concept the value was read from, e.g. "us-gaap:NetIncomeLoss" (M0.5).
    source_concept: Mapped[str | None] = mapped_column(Text)


# ---------- filings (M0.5, append-only) ----------


class Filing(ProvenanceMixin, Base):
    """One SEC filing as listed by the submissions API, per filer entity.

    Append-only: a trigger rejects UPDATE and DELETE. published_at is the EDGAR acceptance
    time (ADR-013); source_url is the filing index page.
    """

    __tablename__ = "filings"
    __table_args__ = (
        *provenance_constraints(),
        CheckConstraint(r"accession_number ~ '^\d{10}-\d{2}-\d{6}$'", name="accession_format"),
        CheckConstraint(r"cik ~ '^\d{10}$'", name="cik_format"),
        CheckConstraint("form <> ''", name="form_not_empty"),
        UniqueConstraint(
            "entity_id", "accession_number", name="uq_filings_entity_id_accession_number"
        ),
        Index("ix_filings_entity_id_filing_date", "entity_id", "filing_date"),
        Index("ix_filings_accession_number", "accession_number"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id"))
    cik: Mapped[str] = mapped_column(Text)
    accession_number: Mapped[str] = mapped_column(Text)
    form: Mapped[str] = mapped_column(Text)
    filing_date: Mapped[date] = mapped_column(Date)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_date: Mapped[date | None] = mapped_column(Date)
    primary_document: Mapped[str | None] = mapped_column(Text)
    primary_doc_description: Mapped[str | None] = mapped_column(Text)
    items: Mapped[str | None] = mapped_column(Text)
    is_xbrl: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_inline_xbrl: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- macro series (M0.6) ----------


class MacroSeries(MutableRowMixin, Base):
    """A FRED series in the registry (config/macro_series.yaml; metadata from FRED, ADR-015)."""

    __tablename__ = "macro_series"
    __table_args__ = (
        CheckConstraint("id ~ '^[A-Z0-9_]+$'", name="id_format"),
        CheckConstraint("term_id ~ '^[a-z][a-z0-9_]*$'", name="term_id_format"),
        CheckConstraint(
            "frequency_short IS NULL OR " + sql_in("frequency_short", FREQUENCIES),
            name="frequency_short",
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # FRED series id, e.g. PAYEMS
    term_id: Mapped[str] = mapped_column(Text)  # glossary term shown for the series
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("100"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id"))
    # From FRED's series endpoint; empty until the first fred.series run.
    title: Mapped[str | None] = mapped_column(Text)
    units: Mapped[str | None] = mapped_column(Text)
    units_short: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str | None] = mapped_column(Text)
    frequency_short: Mapped[str | None] = mapped_column(Text)
    seasonal_adjustment_short: Mapped[str | None] = mapped_column(Text)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MacroObservation(FactMixin, Base):
    """One value of a series for one observation date, as published in one ALFRED vintage.

    A later vintage with a different value is a new version (revision_reason `revision`);
    published_at is the end of the vintage's first day in New York (ADR-012, ADR-015).
    """

    __tablename__ = "macro_observations"
    __fact_key__ = ("series_id", "observation_date")
    __table_args__ = (
        *provenance_constraints(),
        *bitemporal_constraints(),
        CheckConstraint("value NOT IN ('NaN', 'Infinity', '-Infinity')", name="value_finite"),
        CheckConstraint(
            "revision_reason IS NULL OR " + sql_in("revision_reason", REVISION_REASONS),
            name="revision_reason",
        ),
        CheckConstraint(
            "(supersedes_id IS NULL) = (revision_reason IS NULL)",
            name="revision_link",
        ),
        Index(
            "uq_macro_observations_key_version",
            *__fact_key__,
            "version",
            unique=True,
        ),
        # One current version per observation and publication time; also the idempotency key.
        Index(
            "uq_macro_observations_current_key_published",
            *__fact_key__,
            "published_at",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    series_id: Mapped[str] = mapped_column(Text, ForeignKey("macro_series.id"))
    observation_date: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric)
    vintage: Mapped[date] = mapped_column(Date)  # ALFRED realtime_start
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("macro_observations.id")
    )
    revision_reason: Mapped[str | None] = mapped_column(Text)


# ---------- prices (M0.7, TimescaleDB hypertables) ----------


class MarketQuote(ProvenanceMixin, Base):
    """MarketPriceObservation (errata E1): one provider snapshot of an instrument's latest
    trade and quote. Append-only; a hypertable on published_at (the newer of the trade and
    quote times). feed_status is the provider's label at ingest (live_single_venue, or fixture
    for recorded data); the UI derives what to show from it and the quote's age (ADR-017)."""

    __tablename__ = "market_quotes"
    __table_args__ = (
        *provenance_constraints(),
        CheckConstraint(sql_in("feed_status", FEED_STATUSES), name="feed_status"),
        CheckConstraint("adjustment_status = 'raw'", name="adjustment_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        UniqueConstraint(
            "instrument_id", "published_at", name="uq_market_quotes_instrument_id_published_at"
        ),
        Index("ix_market_quotes_symbol_published_at", "symbol", "published_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # The hypertable's time column must be part of every unique index, the key included.
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    symbol: Mapped[str] = mapped_column(Text)
    venue: Mapped[str] = mapped_column(Text)
    bid: Mapped[Decimal | None] = mapped_column(Numeric)
    ask: Mapped[Decimal | None] = mapped_column(Numeric)
    bid_size: Mapped[int | None] = mapped_column(BigInteger)
    ask_size: Mapped[int | None] = mapped_column(BigInteger)
    last: Mapped[Decimal | None] = mapped_column(Numeric)
    last_size: Mapped[int | None] = mapped_column(BigInteger)
    day_open: Mapped[Decimal | None] = mapped_column(Numeric)
    day_high: Mapped[Decimal | None] = mapped_column(Numeric)
    day_low: Mapped[Decimal | None] = mapped_column(Numeric)
    day_volume: Mapped[int | None] = mapped_column(BigInteger)
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric)
    currency: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    feed_status: Mapped[str] = mapped_column(Text)
    adjustment_status: Mapped[str] = mapped_column(Text, server_default=text("'raw'"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PriceBar(FactMixin, Base):
    """A daily bar (consolidated SIP), raw or split-adjusted (ADR-017). Versioned facts: a new
    split re-bases the split-adjusted history, which is stored as new versions (`revision`).
    Raw bars count as public at the end of their New York day (ADR-012); split-adjusted bars
    from when they were fetched. feed_status is end_of_day, or fixture for recorded test data
    (ADR-006). A hypertable on bar_time, so supersedes_id has no foreign key (TimescaleDB cannot
    reference a hypertable row by id alone)."""

    __tablename__ = "price_bars"
    __fact_key__ = ("instrument_id", "adjustment", "bar_time")
    __table_args__ = (
        *provenance_constraints(),
        *bitemporal_constraints(),
        CheckConstraint(sql_in("adjustment", ADJUSTMENTS), name="adjustment"),
        CheckConstraint(sql_in("feed_status", BAR_FEED_STATUSES), name="feed_status"),
        CheckConstraint("close NOT IN ('NaN', 'Infinity', '-Infinity')", name="close_finite"),
        CheckConstraint(
            "revision_reason IS NULL OR " + sql_in("revision_reason", REVISION_REASONS),
            name="revision_reason",
        ),
        CheckConstraint(
            "(supersedes_id IS NULL) = (revision_reason IS NULL)", name="revision_link"
        ),
        Index("uq_price_bars_key_version", *__fact_key__, "version", unique=True),
        Index(
            "uq_price_bars_current_key_published",
            *__fact_key__,
            "published_at",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_price_bars_symbol_bar_date", "symbol", "bar_date"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    symbol: Mapped[str] = mapped_column(Text)
    adjustment: Mapped[str] = mapped_column(Text)
    bar_date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal] = mapped_column(Numeric)
    high: Mapped[Decimal] = mapped_column(Numeric)
    low: Mapped[Decimal] = mapped_column(Numeric)
    close: Mapped[Decimal] = mapped_column(Numeric)
    volume: Mapped[int] = mapped_column(BigInteger)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric)
    trade_count: Mapped[int | None] = mapped_column(BigInteger)
    feed: Mapped[str] = mapped_column(Text)
    feed_status: Mapped[str] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    revision_reason: Mapped[str | None] = mapped_column(Text)

    @property
    def value(self) -> Decimal:
        """The compared value for versioning (apply_versions): the close."""
        return self.close


# ---------- audit (append-only, written by triggers) ----------


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint(sql_in("action", AUDIT_ACTIONS), name="action"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    object_type: Mapped[str] = mapped_column(Text)
    object_id: Mapped[str] = mapped_column(Text)
    before_hash: Mapped[str | None] = mapped_column(Text)
    after_hash: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
