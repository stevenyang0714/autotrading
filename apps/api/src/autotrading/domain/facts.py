"""FinancialFact contract (02 §28, errata E1) and fact-version semantics (ADR-012)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.provenance import Provenance

# restatement: the issuer reported a different value later (new published_at).
# revision: a statistical source revised a value (e.g. an ALFRED vintage).
# correction: we fixed our own error; the old row is superseded in system time.
RevisionReason = Literal["restatement", "revision", "correction"]

FinancialFactKey = tuple[UUID, str, str, date | None, date]


class FinancialFactIn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: UUID
    metric_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Decimal = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    # Describes the filing (e.g. SEC fy/fp), so it is not part of the fact key.
    fiscal_period: str | None = None
    period_start: date | None = None
    period_end: date
    filed_at: AwareDatetime | None = None
    accession_id: str | None = None
    vintage: str | None = None
    # Raw concept the value was read from, e.g. "us-gaap:NetIncomeLoss" (traceability).
    source_concept: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def period_order(self) -> Self:
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self

    def fact_key(self) -> FinancialFactKey:
        """Identity of the logical fact across versions: entity, metric, unit and period."""
        return (self.entity_id, self.metric_id, self.unit, self.period_start, self.period_end)


@dataclass(frozen=True)
class StoredVersion[RefT]:
    """A current (not superseded) version of one fact key, as the version check sees it."""

    ref: RefT
    published_at: datetime
    value: Decimal


@dataclass(frozen=True)
class Unchanged[RefT]:
    """The value was already known at that publication time; nothing to write."""

    version: StoredVersion[RefT]


@dataclass(frozen=True)
class NewVersion[RefT]:
    """Write a new version; `supersedes` is the version it restates (None for the first)."""

    supersedes: StoredVersion[RefT] | None


@dataclass(frozen=True)
class Conflict:
    reason: str


type VersionDecision[RefT] = Unchanged[RefT] | NewVersion[RefT] | Conflict


def decide_version[RefT](
    versions: Sequence[StoredVersion[RefT]], published_at: datetime, value: Decimal
) -> VersionDecision[RefT]:
    """Classify an incoming value against the current versions of its fact key.

    `versions` must be ordered by publication time (ties: storage order). Re-reading old
    filings is harmless: a value equal to the version known at its own publication time is
    unchanged, even after a later restatement. Two values for one publication, or a value
    published before the newest stored version, are conflicts: facts are stored in
    publication order (ADR-012).
    """
    prior: StoredVersion[RefT] | None = None
    newer_exists = False
    for version in versions:
        if version.published_at <= published_at:
            prior = version
        else:
            newer_exists = True
    if prior is not None and prior.value == value:
        return Unchanged(prior)
    if prior is not None and prior.published_at == published_at:
        return Conflict(
            f"two values for one publication at {published_at.isoformat()}: "
            f"{prior.value} stored, {value} received"
        )
    if newer_exists:
        return Conflict(
            f"value published at {published_at.isoformat()} is older than the newest stored version"
        )
    return NewVersion(prior)
