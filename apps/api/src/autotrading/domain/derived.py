"""Derived fundamentals (M1.1, ADR-021): computed at read time from the facts known at a time.

Inputs are the reported values of one period as known at the As known on time, so a derived
value is point-in-time by construction. Each result names its inputs, so the UI can show the
formula with the values and filings behind it.

- free_cash_flow = operating cash flow - capex (both required; capex is a positive payment).
- total_debt = long-term debt, non-current (required) + current portion + commercial paper. A
  current portion or commercial paper the balance sheet does not report counts as 0 and is
  named in `assumed_zero` (Steven's decision D4).
- net_debt = total debt - cash and cash equivalents (cash required).
Never approximated otherwise (ADR-013): a missing required input means no value.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

DERIVED_ANNUAL = ("free_cash_flow",)
DERIVED_BALANCE = ("total_debt", "net_debt")
DEBT_REQUIRED = "long_term_debt_noncurrent"
DEBT_OPTIONAL = ("long_term_debt_current", "commercial_paper")


class ValueFact(Protocol):
    @property
    def metric_id(self) -> str: ...
    @property
    def value(self) -> Decimal: ...
    @property
    def period_start(self) -> date | None: ...
    @property
    def period_end(self) -> date: ...


@dataclass(frozen=True)
class Derived[FactT: ValueFact]:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date
    method: str
    inputs: tuple[tuple[str, FactT | None], ...]  # (metric_id, fact); None = assumed 0
    assumed_zero: tuple[str, ...] = ()


def _period_index[FactT: ValueFact](
    facts: Iterable[FactT],
) -> dict[tuple[str, date | None, date], FactT]:
    return {(f.metric_id, f.period_start, f.period_end): f for f in facts}


def free_cash_flow[FactT: ValueFact](
    index: Mapping[tuple[str, date | None, date], FactT], start: date | None, end: date
) -> Derived[FactT] | None:
    ocf = index.get(("operating_cash_flow", start, end))
    capex = index.get(("capex", start, end))
    if ocf is None or capex is None:
        return None
    return Derived(
        "free_cash_flow",
        ocf.value - capex.value,
        start,
        end,
        "operating_cash_flow - capex",
        (("operating_cash_flow", ocf), ("capex", capex)),
    )


def total_debt[FactT: ValueFact](
    index: Mapping[tuple[str, date | None, date], FactT], end: date
) -> Derived[FactT] | None:
    required = index.get((DEBT_REQUIRED, None, end))
    if required is None:
        return None
    optional = [(m, index.get((m, None, end))) for m in DEBT_OPTIONAL]
    value = required.value + sum((f.value for _, f in optional if f is not None), Decimal(0))
    return Derived(
        "total_debt",
        value,
        None,
        end,
        "long-term debt (non-current + current) + commercial paper",
        ((DEBT_REQUIRED, required), *optional),
        tuple(m for m, f in optional if f is None),
    )


def net_debt[FactT: ValueFact](
    index: Mapping[tuple[str, date | None, date], FactT], end: date
) -> Derived[FactT] | None:
    debt = total_debt(index, end)
    cash = index.get(("cash", None, end))
    if debt is None or cash is None:
        return None
    return Derived(
        "net_debt",
        debt.value - cash.value,
        None,
        end,
        "total debt - cash",
        (*debt.inputs, ("cash", cash)),
        debt.assumed_zero,
    )


def derive_all[FactT: ValueFact](facts: Iterable[FactT]) -> list[Derived[FactT]]:
    """Every derived value the facts allow: FCF per duration period, debt per balance date."""
    index = _period_index(facts)
    durations = {(s, e) for (m, s, e) in index if m == "operating_cash_flow" and s is not None}
    instants = {e for (m, s, e) in index if m == DEBT_REQUIRED and s is None}
    out: list[Derived[FactT]] = []
    for start, end in sorted(durations, key=lambda p: (p[1], p[0] or p[1])):
        if (fcf := free_cash_flow(index, start, end)) is not None:
            out.append(fcf)
    for end in sorted(instants):
        for derive in (total_debt, net_debt):
            if (value := derive(index, end)) is not None:
                out.append(value)
    return out
