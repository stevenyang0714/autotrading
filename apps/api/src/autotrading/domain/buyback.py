"""Buyback record (M1.4a, ADR-025): authorization, actual repurchase and net share reduction of a
company, kept apart (02 §5), as known at a time T. Pure functions over the facts, closes and
splits known at T and the buyback statements published by then.

Per period (TTM when later than the last fiscal year, then five fiscal years; domain/research):
- repurchases: dollars paid and shares bought, as reported (shares on T's split basis);
- intensity: repurchases / market cap at the period end (the last end-of-day close on or before
  it x balance-sheet shares outstanding then, on the close's split basis);
- repurchases / free cash flow; SBC offset = SBC / repurchases;
- debt-funded flag: net debt up over the period while repurchases exceed free cash flow;
- net share reduction (B5) = shares outstanding a year earlier - now, both on T's split basis,
  and as a share of the earlier count; diluted share change as in the Research Record.
Missing inputs are named; non-positive denominators are n/m (ADR-013).

Announcements: statements from 8-Ks and press releases (domain/buyback_announcements) grouped
into events: the same kind and amount within EVENT_DAYS is one event, and so is the same
sentence repeated within REPEAT_DAYS of the event's latest source (a bank restating its program
in each quarter's supplement). An event is dated by its earliest stated or publication date and
keeps every source as evidence. The same sentence a year later is a new event (Apple renews a
$100 billion increase each spring in the same words).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from autotrading.domain.research import Book, Window, growth, percent, periods, valued, with_detail
from autotrading.domain.splits import Split, adjust
from autotrading.domain.valuation import (
    NEW_YORK,
    Close,
    DatedFact,
    Input,
    Unit,
    Valued,
    close_basis,
)

EVENT_DAYS = 30
REPEAT_DAYS = 120  # an identical sentence in the next quarter's filing restates the event
CLOSE_WITHIN = timedelta(days=7)  # a period may end on a weekend or holiday

Section = Literal["repurchase", "shares"]

ROWS: tuple[tuple[Section, str, Unit], ...] = (
    ("repurchase", "share_repurchases", "USD"),
    ("repurchase", "shares_repurchased", "shares"),
    ("repurchase", "buyback_intensity", "percent"),
    ("repurchase", "repurchase_to_fcf", "percent"),
    ("repurchase", "sbc_offset", "percent"),
    ("repurchase", "debt_funded_buyback", "flag"),
    ("shares", "net_share_reduction", "shares"),
    ("shares", "net_share_reduction_pct", "percent"),
    ("shares", "diluted_shares_change", "percent"),
)
BUYBACK_METRICS = (
    "revenue",
    "net_income",
    "operating_cash_flow",
    "capex",
    "share_repurchases",
    "shares_repurchased",
    "stock_based_compensation",
    "shares_outstanding",
    "diluted_shares",
    "cash",
    "long_term_debt_noncurrent",
    "long_term_debt_current",
    "commercial_paper",
)


@dataclass(frozen=True)
class Record[FactT: DatedFact]:
    periods: list[Window]
    rows: list[tuple[Section, str, Unit, list[Valued[FactT]]]]


def close_on(closes: Sequence[Close], day: date) -> Close | None:
    """The last end-of-day close on or before `day`, at most CLOSE_WITHIN earlier."""
    found = [
        c for c in closes if c.feed_status == "end_of_day" and day - CLOSE_WITHIN <= c.day <= day
    ]
    return max(found, key=lambda c: c.day) if found else None


def _on_basis[FactT: DatedFact](
    book: Book[FactT], metric: str, found: Input[FactT] | None, basis: datetime
) -> Input[FactT] | None:
    """A share count moved to the split basis of `basis`; unavailable when its sources were
    reported on different bases (a split inside the period's filings)."""
    if found is None or found.value is None or not found.sources:
        return found
    reported = {f.reported_at for f in found.sources}
    factors = {
        a.factor if (a := adjust(metric, Decimal(1), r, basis, book.splits)) else 1
        for r in reported
    }
    if len(factors) != 1:
        return None
    adjusted = adjust(metric, found.value, min(reported), basis, book.splits)
    if adjusted is None:
        return found
    return Input(
        found.name,
        adjusted.value,
        found.period_start,
        found.period_end,
        found.sources,
        f"split-adjusted from {found.value} (factor {adjusted.factor})",
    )


def market_cap_at[FactT: DatedFact](
    book: Book[FactT], closes: Sequence[Close], day: date
) -> tuple[Input[FactT] | None, list[str]]:
    """Close x shares outstanding at a period end, or what is missing."""
    close = close_on(closes, day)
    shares = book.instant("shares_outstanding", day)
    missing = [
        label
        for label, value in (
            (f"end-of-day close by {day}", close),
            (f"shares outstanding on {day}", shares),
        )
        if value is None
    ]
    if close is None or shares is None:
        return None, missing
    on_basis = _on_basis(book, "shares_outstanding", shares, close_basis(close))
    if on_basis is None or on_basis.value is None:
        return None, [f"shares outstanding on {day} on one split basis"]
    return (
        Input(
            "market_cap",
            (close.close * on_basis.value).quantize(Decimal(1)),
            None,
            day,
            on_basis.sources,
            f"close {close.day} ${close.close} x {on_basis.value} shares outstanding",
        ),
        [],
    )


def _period_values[FactT: DatedFact](
    book: Book[FactT], window: Window, closes: Sequence[Close]
) -> dict[str, Valued[FactT]]:
    out: dict[str, Valued[FactT]] = {}
    paid = book.flow("share_repurchases", window)
    bought = _on_basis(book, "shares_repurchased", book.flow("shares_repurchased", window), book.at)
    fcf, fcf_missing = book.free_cash_flow(window)
    sbc = book.flow("stock_based_compensation", window)
    cap, cap_missing = market_cap_at(book, closes, window.end)

    out["share_repurchases"] = valued(
        "share_repurchases", "USD", [("share repurchases", paid)], lambda v: v[0]
    )
    out["shares_repurchased"] = valued(
        "shares_repurchased", "shares", [("shares repurchased", bought)], lambda v: v[0]
    )
    out["buyback_intensity"] = valued(
        "buyback_intensity",
        "percent",
        [("share repurchases", paid), ("market cap", cap)],
        lambda v: percent(v[0], v[1]),
        [(1, "market cap")],
        {"market cap": cap_missing},
    )
    out["repurchase_to_fcf"] = valued(
        "repurchase_to_fcf",
        "percent",
        [("share repurchases", paid), ("free cash flow", fcf)],
        lambda v: percent(v[0], v[1]),
        [(1, "free cash flow")],
        {"free cash flow": fcf_missing},
    )
    out["sbc_offset"] = valued(
        "sbc_offset",
        "percent",
        [("stock-based compensation", sbc), ("share repurchases", paid)],
        lambda v: percent(v[0], v[1]),
        [(1, "share repurchases")],
    )
    debt_open, debt_close = book.net_debt(window.opening), book.net_debt(window.end)
    out["debt_funded_buyback"] = valued(
        "debt_funded_buyback",
        "flag",
        [
            (f"net debt on {window.opening}", debt_open),
            (f"net debt on {window.end}", debt_close),
            ("share repurchases", paid),
            ("free cash flow", fcf),
        ],
        lambda v: Decimal(1) if v[1] > v[0] and v[2] > v[3] else Decimal(0),
        explain={"free cash flow": fcf_missing},
    )

    before = _on_basis(
        book,
        "shares_outstanding",
        book.instant("shares_outstanding", window.opening),
        book.at,
    )
    now = _on_basis(
        book, "shares_outstanding", book.instant("shares_outstanding", window.end), book.at
    )
    shares_needed: list[tuple[str, Input[FactT] | None]] = [
        (f"shares outstanding on {window.opening}", before),
        (f"shares outstanding on {window.end}", now),
    ]
    out["net_share_reduction"] = valued(
        "net_share_reduction", "shares", shares_needed, lambda v: v[0] - v[1]
    )
    out["net_share_reduction_pct"] = valued(
        "net_share_reduction_pct",
        "percent",
        shares_needed,
        lambda v: percent(v[0] - v[1], v[0]),
        [(0, f"shares outstanding on {window.opening}")],
    )
    shares_now = book.diluted_shares(window, window.end)
    shares_before = book.diluted_shares(window, window.opening)
    out["diluted_shares_change"] = valued(
        "diluted_shares_change",
        "percent",
        [("diluted shares", shares_now), ("diluted shares a year earlier", shares_before)],
        lambda v: growth(v[0], v[1]),
        [(1, "diluted shares a year earlier")],
    )
    flag = out["debt_funded_buyback"]
    out["debt_funded_buyback"] = with_detail(
        flag,
        "net debt rose while repurchases exceeded free cash flow"
        if flag.value == 1
        else "net debt did not rise, or repurchases stayed within free cash flow"
        if flag.value == 0
        else None,
    )
    return out


def buyback_record[FactT: DatedFact](
    facts: Sequence[FactT], closes: Sequence[Close], at: datetime, splits: Sequence[Split]
) -> Record[FactT]:
    """Every row for every period, as known at `at` (facts and closes already filtered)."""
    book = Book(facts, at, splits)
    shown = periods(book)
    by_period = [_period_values(book, w, closes) for w in shown]
    return Record(
        periods=shown,
        rows=[
            (section, metric, unit, [values[metric] for values in by_period])
            for section, metric, unit in ROWS
        ],
    )


# ---------- announcements ----------

Channel = Literal["sec_8k", "press_release"]


@dataclass(frozen=True)
class AnnouncementSource:
    channel: Channel
    kind: str  # new, increase, plan, remaining
    amount: Decimal
    remaining_amount: Decimal | None
    stated_date: date | None
    sentence: str
    url: str
    published_at: datetime
    accession: str | None = None  # 8-K
    document_type: str | None = None  # 8-K, EX-99.1, ...
    title: str | None = None  # press release

    @property
    def day(self) -> date:
        """The announcement's date: as stated in the sentence, else its New York publication
        day."""
        return self.stated_date or self.published_at.astimezone(NEW_YORK).date()


@dataclass
class Event:
    kind: str
    amount: Decimal
    day: date
    sources: list[AnnouncementSource] = field(default_factory=list)

    @property
    def remaining_amount(self) -> Decimal | None:
        stated = [s.remaining_amount for s in self.sources if s.remaining_amount is not None]
        return stated[0] if stated else None

    @property
    def first_published_at(self) -> datetime:
        return min(s.published_at for s in self.sources)


def _identity(source: AnnouncementSource) -> tuple[str, str]:
    """The same sentence of the same filing (an 8-K listed under two co-filing issuers) or of
    the same page counts once."""
    return (source.accession or source.url, source.sentence)


def _same_event(event: Event, source: AnnouncementSource) -> bool:
    if (event.kind, event.amount) != (source.kind, source.amount):
        return False
    if abs((source.day - event.day).days) <= EVENT_DAYS:
        return True
    latest = max(s.day for s in event.sources)
    return (source.day - latest).days <= REPEAT_DAYS and source.sentence in {
        s.sentence for s in event.sources
    }


def events(sources: Sequence[AnnouncementSource], at: datetime) -> list[Event]:
    """Sources published by `at`, grouped: the same kind and amount within EVENT_DAYS is one
    event (an 8-K and its press release, or a later filing repeating a stated date). Newest
    first."""
    grouped: list[Event] = []
    known = sorted(
        (s for s in sources if s.published_at <= at), key=lambda s: (s.day, s.published_at)
    )
    for source in known:
        match = next((e for e in grouped if _same_event(e, source)), None)
        if match is None:
            grouped.append(Event(source.kind, source.amount, source.day, [source]))
        elif _identity(source) not in {_identity(s) for s in match.sources}:
            match.sources.append(source)
    return sorted(grouped, key=lambda e: (e.day, e.first_published_at), reverse=True)
