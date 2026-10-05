"""Provenance contract carried by every stored observation (02 §4, CLAUDE.md, ADR-012).

No provenance, no insert: the database enforces the same fields with NOT NULL constraints.
"""

from datetime import UTC, date, datetime, time
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

# Values of the glossary term `license_status` (docs/glossary/glossary_seed.yaml).
LicenseStatus = Literal[
    "public", "licensed_personal", "licensed_redistribution", "restricted", "unknown"
]
TimePrecision = Literal["exact", "day"]

# ADR-012: date-only publication times are treated as known at the end of that day in New York,
# so a backtest can never see a same-day release (e.g. CPI at 08:30 ET) before it happened.
DATE_ONLY_TIMEZONE = "America/New_York"


def end_of_day(day: date, tz: str = DATE_ONLY_TIMEZONE) -> datetime:
    """Conservative availability time for a date-only publication, returned in UTC."""
    local = datetime.combine(day, time(23, 59, 59, 999999), tzinfo=ZoneInfo(tz))
    return local.astimezone(UTC)


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    source_tier: int = Field(ge=1, le=4)
    source_url: str = Field(min_length=1, pattern=r"^https?://")
    # World knowledge time: when the information became public (ADR-012).
    published_at: AwareDatetime
    published_at_precision: TimePrecision
    ingested_at: AwareDatetime
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None
    as_of: AwareDatetime
    license_status: LicenseStatus
    confidence: float = Field(ge=0, le=1)
    source_timezone: str | None = None
    ingestion_run_id: UUID | None = None
    raw_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    @model_validator(mode="after")
    def effective_range(self) -> Self:
        # Equal bounds are allowed: point-in-time values such as balance-sheet items.
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not be before effective_from")
        return self
