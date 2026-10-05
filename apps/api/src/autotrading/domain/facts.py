"""FinancialFact contract (02 §28, errata E1) and fact-version semantics (ADR-012)."""

from datetime import date
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
    provenance: Provenance

    @model_validator(mode="after")
    def period_order(self) -> Self:
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self

    def fact_key(self) -> FinancialFactKey:
        """Identity of the logical fact across versions: entity, metric, unit and period."""
        return (self.entity_id, self.metric_id, self.unit, self.period_start, self.period_end)
