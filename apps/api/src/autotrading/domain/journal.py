"""Paper journal (M1.6, ADR-027): evidence comparison on replay and paper performance. Pure; no
I/O.

- Evidence (J2): each item of a Thesis Card is a system row read as known at the card's T and
  system time S and stored as a snapshot. A replay reads it again at the same (T, S); the item is
  identical, differs (and in which fields) or missing.
- Paper performance (J3): a TRADE enters at the last end-of-day close known at its T and is
  marked at the last close known at the viewing time, or at its exit decision's close. Splits
  effective in between scale the entry price and quantity (the position is unchanged). The return
  is signed by side; SPY's return over the same closes is shown with the difference in
  percentage points (the position against holding SPY). A NO TRADE shows how the stock moved
  after it, unsigned. Closes only: no costs, slippage, dividends or fills; a limit price is
  recorded, never simulated.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any, Literal

from autotrading.domain.splits import Split, splits_between

EvidenceKind = Literal[
    "financial_fact",
    "filing",
    "buyback_statement",
    "guidance_statement",
    "buyback_state",
    "news",
    "price_close",
]
EVIDENCE_KINDS: tuple[EvidenceKind, ...] = (
    "financial_fact",
    "filing",
    "buyback_statement",
    "guidance_statement",
    "buyback_state",
    "news",
    "price_close",
)
MIN_EVIDENCE, MAX_EVIDENCE = 3, 7  # 02 §17
MAX_CATALYSTS = 5
NoTradeReason = Literal["priced_in", "insufficient_evidence", "excessive_risk", "other"]
Side = Literal["buy", "sell"]
ReplayStatus = Literal["identical", "differs", "missing"]
PERCENT = Decimal("0.01")
CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Comparison:
    status: ReplayStatus
    changed: list[str]  # snapshot fields whose value differs


def compare(stored: Mapping[str, Any], again: Mapping[str, Any] | None) -> Comparison:
    """A stored snapshot against the same row read again at the same (T, S)."""
    if again is None:
        return Comparison("missing", [])
    changed = sorted(k for k in stored.keys() | again.keys() if stored.get(k) != again.get(k))
    return Comparison("differs" if changed else "identical", changed)


@dataclass(frozen=True)
class Mark:
    """An end-of-day close used as a paper price."""

    day: date
    close: Decimal
    published_at: datetime


@dataclass(frozen=True)
class PaperReturn:
    status: Literal["ok", "unavailable"]
    detail: str | None  # why there is no return
    entry: Mark | None
    mark: Mark | None
    split_factor: Decimal  # shares now per share at entry (1 without a split)
    entry_basis: Decimal | None  # the entry close on the mark's split basis
    return_pct: Decimal | None  # signed by side; unsigned for a NO TRADE
    pnl: Decimal | None  # USD; None without a quantity (NO TRADE)
    benchmark_return_pct: Decimal | None
    relative: Decimal | None  # percentage points: return_pct - benchmark_return_pct
    max_loss_breached: bool | None  # None without a maximum loss


def _pct(now: Decimal, then: Decimal) -> Decimal:
    return ((now / then - 1) * 100).quantize(PERCENT)


def _decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def paper_return(
    side: Side | None,
    quantity: Decimal | None,
    entry: Mark | None,
    mark: Mark | None,
    splits: Iterable[Split],
    benchmark_entry: Mark | None,
    benchmark_mark: Mark | None,
    max_loss: Decimal | None = None,
) -> PaperReturn:
    """The paper return from `entry` to `mark`; `side` None for a NO TRADE (unsigned)."""
    if entry is None or mark is None:
        missing = "no end-of-day close at the decision" if entry is None else "no close yet"
        return PaperReturn(
            "unavailable", missing, entry, mark, Decimal(1), None, None, None, None, None, None
        )
    factor = Fraction(1)
    for split in splits_between(splits, entry.published_at, mark.published_at):
        factor *= split.ratio
    basis = Fraction(entry.close) / factor
    sign = -1 if side == "sell" else 1
    return_pct = sign * (Fraction(mark.close) / basis - 1) * 100
    pnl = (
        _decimal(sign * (Fraction(mark.close) - basis) * Fraction(quantity) * factor).quantize(
            CENTS
        )
        if quantity is not None and side is not None
        else None
    )
    benchmark = (
        _pct(benchmark_mark.close, benchmark_entry.close)
        if benchmark_entry is not None
        and benchmark_mark is not None
        and benchmark_mark.day >= benchmark_entry.day
        else None
    )
    rounded = _decimal(return_pct).quantize(PERCENT)
    return PaperReturn(
        status="ok",
        detail=None,
        entry=entry,
        mark=mark,
        split_factor=_decimal(factor),
        entry_basis=_decimal(basis).quantize(Decimal("0.000001")),
        return_pct=rounded,
        pnl=pnl,
        benchmark_return_pct=benchmark,
        relative=(rounded - benchmark) if benchmark is not None else None,
        max_loss_breached=(pnl is not None and -pnl > max_loss) if max_loss is not None else None,
    )
