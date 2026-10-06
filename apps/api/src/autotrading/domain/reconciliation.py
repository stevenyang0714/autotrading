"""Filing reconciliation (M1.1, ADR-021): what a filing's own XBRL says against what we store.

Pure functions; the job reads the instance and the database, this decides.

Fact checks, for every mapped metric and period the filing reports (non-dimensional, the same
concept selection as company facts, plus its class sums):
- match: our value as known at the filing's acceptance time equals the filing's;
- mismatch: it differs;
- missing: we knew no value then;
- extra: we store a value under this filing that the filing does not report;
- restated_later (information only): matched then, but a later filing changed it. This is the
  acceptance case "a mismatch explained by a later restatement": comparing at the filing's own
  time keeps later restatements from counting as errors.
Checks: the balance identity (assets = liabilities and equity) on every balance-sheet date
the filing reports both, quarters differenced from stored
year-to-date values against the three-month values the filing reports, and restatements that
look like an unrecorded split. A filing passes when no fact check fails and no check fails.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Literal

from autotrading.domain.derived import ValueFact
from autotrading.domain.quarters import quarters

METHODOLOGY_VERSION = "0.1.0"
QUARTER_CHECK_METRICS = ("revenue", "gross_profit", "operating_income", "net_income")
FAILING = frozenset({"mismatch", "missing", "extra", "fail", "flag"})

Check = Literal["fact", "identity", "quarter", "split"]
Status = Literal["match", "mismatch", "missing", "extra", "restated_later", "ok", "fail", "flag"]
Key = tuple[str, date | None, date]  # (metric_id, period_start, period_end)


@dataclass(frozen=True)
class Stored:
    value: Decimal
    accession: str | None


@dataclass(frozen=True)
class Item:
    check: Check
    status: Status
    metric_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    filing_value: Decimal | None = None
    stored_value: Decimal | None = None
    current_value: Decimal | None = None
    stored_accession: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Result:
    items: list[Item]

    def count(self, status: Status, check: Check | None = None) -> int:
        return sum(
            1 for i in self.items if i.status == status and (check is None or i.check == check)
        )

    @property
    def passed(self) -> bool:
        return not any(i.status in FAILING for i in self.items)


def fact_items(
    filing: Mapping[Key, Decimal],
    at_filing: Mapping[Key, Stored],
    current: Mapping[Key, Stored],
    under_accession: Iterable[Key],
) -> list[Item]:
    items = []
    for key, value in sorted(
        filing.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1] or kv[0][2])
    ):
        metric, start, end = key
        known, now = at_filing.get(key), current.get(key)
        base = Item("fact", "match", metric, start, end, value)
        if known is None:
            items.append(replace(base, status="missing"))
        elif known.value != value:
            items.append(
                replace(
                    base,
                    status="mismatch",
                    stored_value=known.value,
                    stored_accession=known.accession,
                )
            )
        elif now is not None and now.value != value:
            items.append(
                replace(
                    base,
                    status="restated_later",
                    stored_value=known.value,
                    current_value=now.value,
                    stored_accession=now.accession,
                )
            )
        else:
            items.append(replace(base, stored_value=known.value, stored_accession=known.accession))
    for key in sorted(set(under_accession) - set(filing), key=str):
        metric, start, end = key
        stored = at_filing.get(key) or current.get(key)
        items.append(
            Item(
                "fact",
                "extra",
                metric,
                start,
                end,
                stored_value=stored.value if stored else None,
                detail="stored under this filing, not reported in its XBRL",
            )
        )
    return items


def identity_items(instants: Mapping[tuple[str, date], Decimal]) -> list[Item]:
    """`instants`: (qualified concept, date) -> non-dimensional value from the filing."""
    items = []
    dates = sorted({d for _, d in instants})
    for day in dates:
        assets = instants.get(("us-gaap:Assets", day))
        total = instants.get(("us-gaap:LiabilitiesAndStockholdersEquity", day))
        if assets is not None and total is not None:
            items.append(
                Item(
                    "identity",
                    "ok" if assets == total else "fail",
                    "balance_sheet",
                    None,
                    day,
                    filing_value=assets,
                    stored_value=total,
                    detail="Assets = Liabilities and stockholders' equity",
                )
            )
    return items


def rounding_unit(*values: Decimal) -> Decimal:
    """The coarsest unit all values are rounded to: $1M for 20,441,000,000 (decimals -6)."""
    zeros = []
    for value in values:
        if value == 0:
            continue  # zero is a multiple of any unit
        exponent = value.normalize().as_tuple().exponent  # 20441000000 -> 20441E+6
        zeros.append(max(exponent, 0) if isinstance(exponent, int) else 0)
    return Decimal(10) ** min(zeros) if zeros else Decimal(0)


def quarter_items[FactT: ValueFact](
    stored: Iterable[FactT], filing_three_months: Mapping[Key, Decimal]
) -> list[Item]:
    """Quarters differenced from stored year-to-date values (as known at the filing) against
    the three-month values the filing itself reports. Each figure is rounded on its own (Meta
    reports in millions), so a difference of one rounding unit is within rounding."""
    facts = list(stored)
    items = []
    for metric in QUARTER_CHECK_METRICS:
        for quarter in quarters(facts, metric):
            if quarter.method != "ytd_difference":
                continue
            reported = filing_three_months.get((metric, quarter.period_start, quarter.period_end))
            if reported is None:
                continue
            unit = rounding_unit(reported, *(f.value for f in quarter.inputs))
            difference = abs(reported - quarter.value)
            detail = f"Q{quarter.number} from year-to-date values vs the reported quarter"
            if 0 < difference <= unit:
                detail += f"; within rounding ({unit:,f} per figure)"
            items.append(
                Item(
                    "quarter",
                    "ok" if difference <= unit else "fail",
                    metric,
                    quarter.period_start,
                    quarter.period_end,
                    filing_value=reported,
                    stored_value=quarter.value,
                    detail=detail,
                )
            )
    return items


def split_items(findings: Iterable[str]) -> list[Item]:
    return [Item("split", "flag", detail=finding) for finding in findings]
