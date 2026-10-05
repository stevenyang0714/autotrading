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
REVISION_REASONS = ("restatement", "revision", "correction")
AUDIT_ACTIONS = ("insert", "update", "delete", "supersede")


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
