"""Macro observations (M0.6): one value of a FRED series for one date in one ALFRED vintage.

ADR-015: a vintage starts on `realtime_start`, a date, so it counts as published at the end of
that day in New York (ADR-012). FRED labels every period by its first day.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autotrading.domain.provenance import Provenance

Frequency = Literal["D", "W", "BW", "M", "Q", "SA", "A"]


class MacroObservationIn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    series_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    observation_date: date
    value: Decimal = Field(allow_inf_nan=False)
    vintage: date  # ALFRED realtime_start
    provenance: Provenance

    def fact_key(self) -> tuple[str, date]:
        return (self.series_id, self.observation_date)


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period_end(start: date, frequency: Frequency) -> date:
    """Last day of the period FRED labels with `start` (its first day)."""
    match frequency:
        case "D":
            return start
        case "W":
            return start + timedelta(days=6)
        case "BW":
            return start + timedelta(days=13)
        case "M":
            return _add_months(start, 1) - timedelta(days=1)
        case "Q":
            return _add_months(start, 3) - timedelta(days=1)
        case "SA":
            return _add_months(start, 6) - timedelta(days=1)
        case "A":
            return _add_months(start, 12) - timedelta(days=1)
