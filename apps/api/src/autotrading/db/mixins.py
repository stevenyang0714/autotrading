"""Reusable column sets.

- MutableRowMixin: reference/config rows (created_at, updated_at, version; a trigger bumps them).
- ProvenanceMixin: provenance every stored observation carries (02 §4, CLAUDE.md).
- BitemporalMixin: append-only fact versions (ADR-007, ADR-012). The database sets
  recorded_at and superseded_at from its own clock; the only permitted UPDATE is superseding.

Mixins do not define the primary key: TimescaleDB hypertables (price bars, M0.7) need the
time column in every unique index, so each fact table declares its own key.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

# Glossary term `license_status` (docs/glossary/glossary_seed.yaml); keep the two in step.
LICENSE_STATUSES = (
    "public",
    "licensed_personal",
    "licensed_redistribution",
    "restricted",
    "unknown",
)
TIME_PRECISIONS = ("exact", "day")


def sql_in(column: str, values: tuple[str, ...]) -> str:
    """CHECK clause `column IN (...)` for a fixed set of string codes."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class MutableRowMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )
    version: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), server_onupdate=FetchedValue()
    )


class ProvenanceMixin:
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id"))
    source_tier: Mapped[int] = mapped_column(SmallInteger, ForeignKey("source_tiers.tier"))
    source_url: Mapped[str] = mapped_column(Text)
    # World knowledge time (ADR-012): when the information became public.
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at_precision: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    license_status: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    source_timezone: Mapped[str | None] = mapped_column(Text)
    # Links to the ingestion run and raw payload that produced the row (M0.3).
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ingestion_runs.id")
    )
    raw_payload_sha256: Mapped[str | None] = mapped_column(Text)


def provenance_constraints() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(sql_in("published_at_precision", TIME_PRECISIONS), name="precision"),
        CheckConstraint(sql_in("license_status", LICENSE_STATUSES), name="license_status"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="effective_range"
        ),
        CheckConstraint("source_url ~ '^https?://'", name="source_url_scheme"),
        CheckConstraint(
            "raw_payload_sha256 IS NULL OR raw_payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="payload_sha256",
        ),
    )


class BitemporalMixin:
    # Columns identifying the logical fact across versions; set by each fact model.
    __fact_key__: ClassVar[tuple[str, ...]]

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
    version: Mapped[int] = mapped_column(Integer)


class FactMixin(ProvenanceMixin, BitemporalMixin):
    """Provenance + system time: the column set of every fact table."""


def bitemporal_constraints() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= recorded_at", name="system_time_order"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )
