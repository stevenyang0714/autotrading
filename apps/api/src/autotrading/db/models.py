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
NEWS_KINDS = ("article", "press_release", "official")
NEWS_TIME_BASES = ("publisher", "first_seen")
DATA_MODES = ("live", "fixture")
SPLIT_KINDS = ("forward_split", "reverse_split", "stock_dividend")
MENTION_RULES = ("exchange_ticker", "feed_issuer", "company_name", "bare_ticker")
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
    # Data-quality notes from the job, e.g. a correction it applied to the source (migration 0011).
    notes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
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


# ---------- news (M0.8) ----------


class NewsItem(ProvenanceMixin, Base):
    """One news article or official release (ADR-018): metadata and a short summary only, never
    the article text. Append-only: a trigger rejects UPDATE and DELETE.

    Provenance: source_id is the feed or GDELT; source_tier is the publisher's own tier
    (config/news_publishers.yaml for GDELT); source_url is the request that returned it.
    published_at is the publisher's time (time_basis publisher) or, for GDELT, when GDELT first
    saw the article (first_seen), which is never earlier than its publication.
    duplicate_group_id ties copies of one story together (domain/news.py); it is set at insert
    and never changes. data_mode fixture marks recorded test data (ADR-006).
    """

    __tablename__ = "news_items"
    __table_args__ = (
        *provenance_constraints(),
        CheckConstraint(sql_in("kind", NEWS_KINDS), name="kind"),
        CheckConstraint(sql_in("time_basis", NEWS_TIME_BASES), name="time_basis"),
        CheckConstraint(sql_in("data_mode", DATA_MODES), name="data_mode"),
        CheckConstraint("url ~ '^https?://'", name="url_scheme"),
        CheckConstraint("canonical_url ~ '^https://'", name="canonical_url_scheme"),
        CheckConstraint("length(title) BETWEEN 1 AND 500", name="title_length"),
        CheckConstraint("snippet IS NULL OR length(snippet) <= 300", name="snippet_length"),
        UniqueConstraint("canonical_url", name="uq_news_items_canonical_url"),
        Index("ix_news_items_published_at", "published_at"),
        Index("ix_news_items_duplicate_group_id", "duplicate_group_id"),
        Index("ix_news_items_source_id_published_at", "source_id", "published_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    title_key: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    publisher_domain: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    source_country: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    time_basis: Mapped[str] = mapped_column(Text)
    publisher_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duplicate_group_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    data_mode: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NewsMention(Base):
    """A universe company named in a news item (rule-based, domain/news.py). Append-only;
    a new extractor version adds rows instead of changing old ones."""

    __tablename__ = "news_mentions"
    __table_args__ = (
        CheckConstraint(sql_in("rule", MENTION_RULES), name="rule"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        UniqueConstraint(
            "news_item_id",
            "instrument_id",
            "extractor_version",
            name="uq_news_mentions_news_item_id_instrument_id_extractor_version",
        ),
        Index("ix_news_mentions_ticker", "ticker"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    news_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("news_items.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    ticker: Mapped[str] = mapped_column(Text)
    rule: Mapped[str] = mapped_column(Text)
    matched_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    extractor_version: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- corporate actions (M1.1) ----------


class SplitEvent(ProvenanceMixin, Base):
    """A stock split of an instrument (ADR-021): `new_rate` shares for every `old_rate` from the
    ex-date on. Append-only: a trigger rejects UPDATE and DELETE.

    From Alpaca corporate actions (2016 on) or the reviewed list config/splits.yaml (earlier
    splits, each citing the issuer's 8-K). published_at is the start of the ex-date in New York:
    a split is announced weeks before, so this is never early.
    """

    __tablename__ = "split_events"
    __table_args__ = (
        *provenance_constraints(),
        CheckConstraint(sql_in("kind", SPLIT_KINDS), name="kind"),
        CheckConstraint("old_rate > 0 AND new_rate > 0", name="rates_positive"),
        UniqueConstraint("instrument_id", "ex_date", name="uq_split_events_instrument_id_ex_date"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    symbol: Mapped[str] = mapped_column(Text)
    ex_date: Mapped[date] = mapped_column(Date)
    old_rate: Mapped[Decimal] = mapped_column(Numeric)
    new_rate: Mapped[Decimal] = mapped_column(Numeric)
    kind: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- buyback announcements (M1.4a) ----------

BUYBACK_STATEMENT_KINDS = ("new", "increase", "plan", "remaining")


class FilingBuybackStatement(ProvenanceMixin, Base):
    """A repurchase authorization, plan or remaining amount stated in an 8-K document (ADR-025
    B1): the sentence (at most 300 characters, never the document), its amount and kind, read by
    `sec.eight_k` with one extractor version. Append-only: a trigger rejects UPDATE and DELETE.
    published_at is the filing's EDGAR acceptance time; source_url the document."""

    __tablename__ = "filing_buyback_statements"
    __table_args__ = (
        *provenance_constraints(),
        CheckConstraint(r"accession_number ~ '^\d{10}-\d{2}-\d{6}$'", name="accession_format"),
        CheckConstraint(sql_in("kind", BUYBACK_STATEMENT_KINDS), name="kind"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "remaining_amount IS NULL OR remaining_amount > 0", name="remaining_positive"
        ),
        CheckConstraint("length(sentence) BETWEEN 1 AND 300", name="sentence_length"),
        UniqueConstraint(
            "entity_id",
            "source_url",
            "sentence",
            "extractor_version",
            name="uq_filing_buyback_statements_source_sentence",
        ),
        Index("ix_filing_buyback_statements_entity_id_published_at", "entity_id", "published_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id"))
    accession_number: Mapped[str] = mapped_column(Text)
    document: Mapped[str] = mapped_column(Text)  # file name in the filing folder
    document_type: Mapped[str] = mapped_column(Text)  # 8-K, EX-99.1, ...
    kind: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric)  # USD
    remaining_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    stated_date: Mapped[date | None] = mapped_column(Date)
    sentence: Mapped[str] = mapped_column(Text)
    rule: Mapped[str] = mapped_column(Text)
    extractor_version: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- earnings guidance (M1.5) ----------

GUIDANCE_METRICS = (
    "revenue",
    "revenue_growth",
    "eps",
    "gross_margin",
    "operating_margin",
    "net_margin",
)


class FilingGuidanceStatement(ProvenanceMixin, Base):
    """A revenue, EPS or margin outlook stated in an exhibit of an earnings 8-K (ADR-026 E3,
    P1-3): the metric, its range, unit and period as written, and the sentence (at most 300
    characters, never the document), read by `sec.earnings_release` with one extractor version.
    Append-only: a trigger rejects UPDATE and DELETE. published_at is the filing's EDGAR
    acceptance time; source_url the document."""

    __tablename__ = "filing_guidance_statements"
    __table_args__ = (
        *provenance_constraints(),
        CheckConstraint(r"accession_number ~ '^\d{10}-\d{2}-\d{6}$'", name="accession_format"),
        CheckConstraint(sql_in("metric", GUIDANCE_METRICS), name="metric"),
        CheckConstraint(sql_in("unit", ("USD", "USD/shares", "percent")), name="unit"),
        CheckConstraint("low <= high", name="range_order"),
        CheckConstraint(sql_in("rule", ("sentence", "outlook_section")), name="rule"),
        CheckConstraint("length(sentence) BETWEEN 1 AND 300", name="sentence_length"),
        UniqueConstraint(
            "entity_id",
            "source_url",
            "metric",
            "low",
            "high",
            "adjusted",
            "extractor_version",
            name="uq_filing_guidance_statements_source_value",
        ),
        Index("ix_filing_guidance_statements_entity_id_published_at", "entity_id", "published_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id"))
    accession_number: Mapped[str] = mapped_column(Text)
    document: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(Text)  # EX-99.1, ...
    metric: Mapped[str] = mapped_column(Text)
    low: Mapped[Decimal] = mapped_column(Numeric)
    high: Mapped[Decimal] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(Text)
    period_text: Mapped[str] = mapped_column(Text)
    adjusted: Mapped[bool] = mapped_column(Boolean)
    sentence: Mapped[str] = mapped_column(Text)
    rule: Mapped[str] = mapped_column(Text)
    extractor_version: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- valuation assumptions (M1.3a) ----------


class ValuationAssumptionSet(Base):
    """One version of a company's fair-value assumptions (ADR-023), saved by Steven on the
    instrument page. Append-only (a trigger rejects UPDATE and DELETE) and audited: a change is
    a new version, so every earlier valuation stays reproducible."""

    __tablename__ = "valuation_assumptions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("length(reason) BETWEEN 1 AND 500", name="reason_length"),
        UniqueConstraint(
            "instrument_id", "version", name="uq_valuation_assumptions_instrument_id_version"
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    version: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- buyback states (M1.4b) ----------

BUYBACK_STATES = ("none", "watch", "active", "high_conviction")  # TRADE-READY: Phase 2 (P1-4)
EVALUATION_TRIGGERS = ("schedule", "manual", "backfill", "replay")


class BuybackRuleSet(Base):
    """One released rule_version of config/buyback_rules.yaml (ADR-025 B4), loaded by `make
    migrate` with the sha256 of its content. Append-only and audited: a released version never
    changes, so every stored state assignment can be recomputed with the rules it used."""

    __tablename__ = "buyback_rule_sets"
    __table_args__ = (
        CheckConstraint(r"rule_version ~ '^\d+\.\d+\.\d+$'", name="rule_version_format"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        UniqueConstraint("rule_version", name="uq_buyback_rule_sets_rule_version"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    rule_version: Mapped[str] = mapped_column(Text)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_sha256: Mapped[str] = mapped_column(Text)
    approved: Mapped[date] = mapped_column(Date)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuybackStateAssignment(Base):
    """One evaluation of a company's buyback state (ADR-025, errata E7): at known_at (T), as the
    database held it at system_time, under one rule version. `assessment` keeps every
    condition's value, threshold, inputs and evidence, and the score with its components, so
    recomputing with the same T, system_time and rule version gives the same row. Backfilled
    rows were computed later than T (month ends since 2021, B6). Append-only."""

    __tablename__ = "buyback_state_assignments"
    __table_args__ = (
        CheckConstraint(sql_in("state", BUYBACK_STATES), name="state"),
        CheckConstraint(sql_in("trigger", EVALUATION_TRIGGERS), name="trigger"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
        CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        UniqueConstraint(
            "instrument_id",
            "known_at",
            "rule_version",
            name="uq_buyback_state_assignments_instrument_known_at_rule",
        ),
        Index("ix_buyback_state_assignments_rule_version_known_at", "rule_version", "known_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    ticker: Mapped[str] = mapped_column(Text)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    system_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rule_version: Mapped[str] = mapped_column(Text, ForeignKey("buyback_rule_sets.rule_version"))
    extractor_version: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSONB)
    backfilled: Mapped[bool] = mapped_column(Boolean)
    trigger: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------- paper journal (M1.6) ----------

SIGNAL_DIRECTIONS = ("long", "short", "neutral")
DECISIONS = ("trade", "no_trade")
SIDES = ("buy", "sell")
ORDER_TYPES = ("market", "limit")
NO_TRADE_REASONS = ("priced_in", "insufficient_evidence", "excessive_risk", "other")
JOURNAL_USER = "steven"  # one user, kept per errata E1


class SignalRecord(Base):
    """A rule's signal (ADR-027 J1; 02 §28, errata E1): family, strategy, rule version, score,
    direction and the observations behind it, as of the time it was generated (T) and the
    database's system time. Phase 1 signals are paper_only. Append-only."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(sql_in("direction", SIGNAL_DIRECTIONS), name="direction"),
        CheckConstraint("execution_eligibility = 'paper_only'", name="paper_only"),
        CheckConstraint("source_quality BETWEEN 1 AND 4", name="source_quality_range"),
        CheckConstraint("evidence_independence >= 0", name="evidence_independence_positive"),
        CheckConstraint("system_time >= generated_at", name="system_time_after_generated_at"),
        UniqueConstraint(
            "instrument_id",
            "family_id",
            "generated_at",
            "rule_version",
            name="uq_signals_instrument_family_time_rule",
        ),
        Index("ix_signals_generated_at", "generated_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    family_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("signal_families.id"))
    strategy_id: Mapped[str | None] = mapped_column(Text, ForeignKey("strategies.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    ticker: Mapped[str] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(Text)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    direction: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    system_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observation_ids: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    source_quality: Mapped[int] = mapped_column(SmallInteger)
    evidence_independence: Mapped[int] = mapped_column(SmallInteger)
    execution_eligibility: Mapped[str] = mapped_column(Text)
    backfilled: Mapped[bool] = mapped_column(Boolean)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ThesisCard(Base):
    """One version of a Thesis Card (ADR-027; 02 §17): thesis, 3-7 evidence items (each a
    snapshot of a system row as known at T, J2), catalysts, invalidation and the valuation it
    relies on, written at T = system time. A change is a new version of the same card_id.
    Append-only and audited."""

    __tablename__ = "thesis_cards"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("length(thesis) BETWEEN 1 AND 400", name="thesis_length"),
        CheckConstraint("length(invalidation) BETWEEN 1 AND 500", name="invalidation_length"),
        CheckConstraint("notes IS NULL OR length(notes) <= 2000", name="notes_length"),
        CheckConstraint("jsonb_array_length(evidence) BETWEEN 3 AND 7", name="evidence_count"),
        CheckConstraint("jsonb_array_length(catalysts) <= 5", name="catalyst_count"),
        CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        CheckConstraint(f"user_id = '{JOURNAL_USER}'", name="single_user"),
        UniqueConstraint("card_id", "version", name="uq_thesis_cards_card_id_version"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    card_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    ticker: Mapped[str] = mapped_column(Text)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    system_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    thesis: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    catalysts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    invalidation: Mapped[str] = mapped_column(Text)
    valuation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    signal_ids: Mapped[list[str]] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TradeDecision(Base):
    """A decision on a Thesis Card (ADR-027; 02 §28, errata E1): a paper TRADE or an explicit NO
    TRADE, recorded alike. A TRADE stores the last end-of-day close known at T (the paper entry
    or exit price; nothing is ever sent). Phase 1 limits are checks (P1-6): paper mode, no broker,
    risk check or portfolio snapshot, approval state `recorded`. An exit is a new decision that
    points at its entry. Append-only and audited."""

    __tablename__ = "trade_decisions"
    __table_args__ = (
        CheckConstraint(sql_in("decision", DECISIONS), name="decision"),
        CheckConstraint(f"side IS NULL OR {sql_in('side', SIDES)}", name="side"),
        CheckConstraint(
            f"order_type IS NULL OR {sql_in('order_type', ORDER_TYPES)}", name="order_type"
        ),
        CheckConstraint(
            f"no_trade_reason IS NULL OR {sql_in('no_trade_reason', NO_TRADE_REASONS)}",
            name="no_trade_reason",
        ),
        CheckConstraint(
            "(decision = 'trade' AND side IS NOT NULL AND quantity > 0 AND order_type IS NOT NULL"
            " AND no_trade_reason IS NULL AND entry_close IS NOT NULL)"
            " OR (decision = 'no_trade' AND side IS NULL AND quantity IS NULL"
            " AND order_type IS NULL AND exits_decision_id IS NULL"
            " AND no_trade_reason IS NOT NULL)",
            name="decision_fields",
        ),
        CheckConstraint("(order_type = 'limit') = (limit_price IS NOT NULL)", name="limit_price"),
        CheckConstraint("limit_price IS NULL OR limit_price > 0", name="limit_price_positive"),
        CheckConstraint("max_loss IS NULL OR max_loss > 0", name="max_loss_positive"),
        CheckConstraint("no_trade_reason <> 'other' OR note IS NOT NULL", name="other_reason_note"),
        CheckConstraint("note IS NULL OR length(note) <= 1000", name="note_length"),
        CheckConstraint("mode = 'paper'", name="paper_mode"),
        CheckConstraint("broker IS NULL", name="no_broker"),
        CheckConstraint("risk_check_id IS NULL", name="no_risk_check"),
        CheckConstraint("portfolio_snapshot_id IS NULL", name="no_portfolio_snapshot"),
        CheckConstraint("approval_state = 'recorded'", name="approval_state"),
        CheckConstraint("system_time >= known_at", name="system_time_after_known_at"),
        CheckConstraint(f"user_id = '{JOURNAL_USER}'", name="single_user"),
        Index(
            "uq_trade_decisions_exits_decision_id",
            "exits_decision_id",
            unique=True,
            postgresql_where=text("exits_decision_id IS NOT NULL"),
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    thesis_card_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("thesis_cards.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("instruments.id"))
    ticker: Mapped[str] = mapped_column(Text)
    strategy_id: Mapped[str | None] = mapped_column(Text, ForeignKey("strategies.id"))
    signal_ids: Mapped[list[str]] = mapped_column(JSONB)
    decision: Mapped[str] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    order_type: Mapped[str | None] = mapped_column(Text)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric)
    max_loss: Mapped[Decimal | None] = mapped_column(Numeric)
    no_trade_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    exits_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("trade_decisions.id")
    )
    entry_close: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(Text)
    broker: Mapped[str | None] = mapped_column(Text)
    risk_check_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    portfolio_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approval_state: Mapped[str] = mapped_column(Text)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    system_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- filing reconciliation (M1.1) ----------

RECONCILIATION_CHECKS = ("fact", "identity", "quarter", "split")
RECONCILIATION_STATUSES = (
    "match",
    "mismatch",
    "missing",
    "extra",
    "restated_later",
    "ok",
    "fail",
    "flag",
)


class FilingReconciliation(Base):
    """One filing checked against its own XBRL instance at one methodology version (ADR-021).
    Append-only: a trigger rejects UPDATE and DELETE."""

    __tablename__ = "filing_reconciliations"
    __table_args__ = (
        CheckConstraint(sql_in("status", ("pass", "warn", "fail")), name="status"),
        CheckConstraint("source_url ~ '^https://'", name="source_url_scheme"),
        UniqueConstraint(
            "entity_id",
            "accession_number",
            "methodology_version",
            name="uq_filing_reconciliations_filing_version",
        ),
        Index("ix_filing_reconciliations_entity_id_form", "entity_id", "form"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id"))
    accession_number: Mapped[str] = mapped_column(Text)
    form: Mapped[str] = mapped_column(Text)
    filing_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(Text)  # the instance
    raw_payload_sha256: Mapped[str] = mapped_column(Text)
    methodology_version: Mapped[str] = mapped_column(Text)
    checked: Mapped[int] = mapped_column(Integer)
    matched: Mapped[int] = mapped_column(Integer)
    mismatched: Mapped[int] = mapped_column(Integer)
    missing: Mapped[int] = mapped_column(Integer)
    extra: Mapped[int] = mapped_column(Integer)
    restated_later: Mapped[int] = mapped_column(Integer)
    checks_failed: Mapped[int] = mapped_column(Integer)
    checks_flagged: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ingestion_runs.id"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReconciliationItem(Base):
    """One check of a filing reconciliation. Append-only."""

    __tablename__ = "reconciliation_items"
    __table_args__ = (
        CheckConstraint(sql_in("check_kind", RECONCILIATION_CHECKS), name="check_kind"),
        CheckConstraint(sql_in("status", RECONCILIATION_STATUSES), name="status"),
        Index("ix_reconciliation_items_reconciliation_id", "reconciliation_id"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (SQLAlchemy reads it per class)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        # Named explicitly: the convention's name would pass Postgres's 63-character limit.
        ForeignKey("filing_reconciliations.id", name="fk_reconciliation_items_reconciliation_id"),
    )
    check_kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    metric_id: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    filing_value: Mapped[Decimal | None] = mapped_column(Numeric)
    stored_value: Mapped[Decimal | None] = mapped_column(Numeric)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric)
    stored_accession: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)


# ---------- audit (append-only, written by triggers) ----------


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(sql_in("action", AUDIT_ACTIONS), name="action"),
        Index("ix_audit_log_object_type_object_id_id", "object_type", "object_id", "id"),
    )

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
