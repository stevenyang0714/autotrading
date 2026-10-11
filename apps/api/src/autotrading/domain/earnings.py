"""Earnings events (M1.5, ADR-026): when results were announced, the reported quarter against
the quarter before and a year earlier, and the price reaction against SPY. Pure functions over
data known at a time T; no I/O. Consensus has no source (OD-3): never estimated (errata E6).

- Event: an 8-K with Item 2.02, at its EDGAR acceptance time (01 §23), classified as before the
  open, during the session or after the close of its New York day.
- Report (E2): the first 10-Q or 10-K the issuer chain files from two days before the event on,
  for a period that ended in the 100 days before it. Actuals wait for it: the release itself has
  no XBRL.
- Actuals: revenue, diluted EPS (reported three-month values only; a fourth quarter is never
  derived, ADR-013), gross / operating / net margin and free cash flow of the report's quarter,
  against the quarter before and the same quarter a year earlier.
- Reaction (E4): from the last close at or before the event to the first close after it
  (day 0), and to the 1st and 5th sessions after day 0; the stock's return minus SPY's over the
  same days, in percentage points. Volume on day 0 against the 20 sessions up to the last close
  before. End-of-day closes known at T only, split-adjusted to T's basis.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from autotrading.domain.market_calendar import NEW_YORK, MarketCalendar
from autotrading.domain.quarters import Quarter, free_cash_flow_quarters, quarters
from autotrading.domain.research import growth, percent
from autotrading.domain.splits import Split, adjust
from autotrading.domain.valuation import RATIO, DatedFact, Input

Timing = Literal["pre_market", "market_hours", "after_hours", "non_session"]
REPORT_FORMS = ("10-Q", "10-K")
REPORT_BEFORE = timedelta(days=2)  # a 10-Q filed just before the release still matches
PERIOD_WITHIN = timedelta(days=100)  # the report's period ended at most this long before
BASE_WITHIN = timedelta(days=7)  # the last close before the event, at most this old
WINDOWS: tuple[tuple[str, int], ...] = (("day 0", 0), ("day +1", 1), ("day +5", 5))
VOLUME_SESSIONS = 20
REGULAR_CLOSE = time(16, 0)


# ---------- timing ----------


def session_close(day: date, calendar: MarketCalendar) -> datetime:
    """When the session of `day` closed: the calendar's close, else 16:00 New York."""
    session = calendar.session(day)
    if session is not None:
        return session.close
    return datetime.combine(day, REGULAR_CLOSE, NEW_YORK)


def timing(at: datetime, calendar: MarketCalendar, sessions: frozenset[date]) -> Timing:
    """Before the open, during the session or after the close of `at`'s New York day; a day
    without a session (weekend, holiday) when `sessions` (days with a benchmark close) cover it."""
    day = at.astimezone(NEW_YORK).date()
    session = calendar.session(day)
    covered = bool(sessions) and day <= max(sessions)
    if session is None or (covered and day not in sessions):
        return "non_session"
    if at < session.open:
        return "pre_market"
    return "market_hours" if at < session.close else "after_hours"


# ---------- reaction ----------


@dataclass(frozen=True)
class DayBar:
    day: date
    close: Decimal
    volume: int | None
    feed_status: str
    published_at: datetime


@dataclass(frozen=True)
class ReactionWindow:
    label: str  # day 0, day +1, day +5
    sessions_after: int
    day: date | None
    stock_return: Decimal | None  # percent
    benchmark_return: Decimal | None  # percent
    relative: Decimal | None  # percentage points (E4)
    detail: str | None  # why it is unavailable


@dataclass(frozen=True)
class Reaction:
    base_day: date | None  # the last close at or before the event
    base_close: Decimal | None
    windows: list[ReactionWindow]
    volume_ratio: Decimal | None  # x
    volume_detail: str | None
    detail: str | None  # why the whole reaction is unavailable


def _usable(bars: Sequence[DayBar], at: datetime, splits: Sequence[Split]) -> list[DayBar]:
    """End-of-day bars public at T, oldest first, closes and volumes on T's split basis."""
    out = []
    for bar in sorted(bars, key=lambda b: b.day):
        if bar.feed_status != "end_of_day" or bar.published_at > at:
            continue
        basis = datetime.combine(bar.day, time(23, 59, 59), NEW_YORK)
        close = adjust("close", bar.close, basis, at, splits)
        volume = (
            adjust("volume", Decimal(bar.volume), basis, at, splits)
            if bar.volume is not None
            else None
        )
        out.append(
            DayBar(
                bar.day,
                close.value if close else bar.close,
                int(volume.value) if volume else bar.volume,
                bar.feed_status,
                bar.published_at,
            )
        )
    return out


def _return(now: Decimal, before: Decimal) -> Decimal:
    return ((now / before - 1) * 100).quantize(RATIO)


def reaction(
    event_at: datetime,
    stock: Sequence[DayBar],
    benchmark: Sequence[DayBar],
    at: datetime,
    calendar: MarketCalendar,
    splits: Sequence[Split],
) -> Reaction:
    """The stock's and SPY's returns from the last close before the event, as known at T."""
    own = _usable(stock, at, splits)
    spy = {b.day: b for b in _usable(benchmark, at, [])}
    before = [b for b in own if session_close(b.day, calendar) <= event_at]
    after = [b for b in own if session_close(b.day, calendar) > event_at]
    base = before[-1] if before else None
    event_day = event_at.astimezone(NEW_YORK).date()
    if base is None or event_day - base.day > BASE_WITHIN:
        return Reaction(
            None, None, [], None, None, "no end-of-day close in the week before the event"
        )
    windows = []
    for label, n in WINDOWS:
        bar = after[n] if len(after) > n else None
        if bar is None:
            windows.append(
                ReactionWindow(label, n, None, None, None, None, "no end-of-day close yet")
            )
            continue
        own_return = _return(bar.close, base.close)
        theirs = (
            _return(spy[bar.day].close, spy[base.day].close)
            if bar.day in spy and base.day in spy
            else None
        )
        windows.append(
            ReactionWindow(
                label,
                n,
                bar.day,
                own_return,
                theirs,
                (own_return - theirs) if theirs is not None else None,
                None if theirs is not None else f"no SPY close on {bar.day} or {base.day}",
            )
        )
    history = [b.volume for b in before[-VOLUME_SESSIONS:] if b.volume is not None]
    day0 = after[0] if after else None
    if day0 is None or day0.volume is None:
        ratio, ratio_detail = None, "no end-of-day close yet"
    elif len(history) < VOLUME_SESSIONS or not sum(history):
        ratio, ratio_detail = None, f"{len(history)} sessions of volume; {VOLUME_SESSIONS} needed"
    else:
        average = Decimal(sum(history)) / len(history)
        ratio, ratio_detail = (Decimal(day0.volume) / average).quantize(RATIO), None
    return Reaction(base.day, base.close, windows, ratio, ratio_detail, None)


# ---------- the report and its actuals ----------


@dataclass(frozen=True)
class Report:
    accession: str
    form: str
    published_at: datetime
    period_end: date
    url: str


def match_report(event_at: datetime, reports: Sequence[Report]) -> Report | None:
    """The first 10-Q or 10-K for a period ending in the 100 days before the event, filed from
    two days before it on (E2)."""
    day = event_at.astimezone(NEW_YORK).date()
    found = [
        r
        for r in reports
        if r.form in REPORT_FORMS
        and r.published_at >= event_at - REPORT_BEFORE
        and day - PERIOD_WITHIN <= r.period_end <= day
    ]
    return min(found, key=lambda r: r.published_at) if found else None


ActualMetric = Literal[
    "revenue", "eps_diluted", "gross_margin", "operating_margin", "net_margin", "free_cash_flow"
]
ACTUAL_UNITS: dict[ActualMetric, str] = {
    "revenue": "USD",
    "eps_diluted": "USD/shares",
    "gross_margin": "percent",
    "operating_margin": "percent",
    "net_margin": "percent",
    "free_cash_flow": "USD",
}
_MARGIN_PARTS = {
    "gross_margin": "gross_profit",
    "operating_margin": "operating_income",
    "net_margin": "net_income",
}
ACTUAL_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capex",
)


@dataclass(frozen=True)
class QuarterValue[FactT: DatedFact]:
    period_start: date | None
    period_end: date | None
    value: Decimal | None
    detail: str | None  # why it is unavailable, or how it was derived
    inputs: tuple[Input[FactT], ...] = ()


@dataclass(frozen=True)
class Actual[FactT: DatedFact]:
    metric: ActualMetric
    unit: str
    current: QuarterValue[FactT]
    prior_quarter: QuarterValue[FactT]
    year_ago: QuarterValue[FactT]
    change_qoq: Decimal | None  # percent for amounts, percentage points for margins
    change_yoy: Decimal | None
    change_unit: Literal["percent", "percentage points"]


def _quarter_input[FactT: DatedFact](
    q: Quarter[FactT], at: datetime, splits: Sequence[Split]
) -> Input[FactT]:
    value, notes = q.value, [] if q.method == "reported" else [q.method.replace("_", " ")]
    if q.metric_id == "eps_diluted":
        moved = adjust("eps_diluted", q.value, q.inputs[0].reported_at, at, splits)
        if moved is not None:
            value = moved.value
            notes.append(f"split-adjusted from {q.value} (factor {moved.factor})")
    return Input(
        q.metric_id, value, q.period_start, q.period_end, q.inputs, "; ".join(notes) or None
    )


def _find[FactT: DatedFact](
    series: Sequence[Quarter[FactT]], end: date, slack: int = 0
) -> Quarter[FactT] | None:
    found = [q for q in series if abs((q.period_end - end).days) <= slack]
    return min(found, key=lambda q: abs((q.period_end - end).days)) if found else None


def actual_series[FactT: DatedFact](facts: Sequence[FactT]) -> dict[str, list[Quarter[FactT]]]:
    """The quarter series the actuals read, computed once per company."""
    series = {m: quarters(facts, m) for m in ACTUAL_METRICS}
    series["free_cash_flow"] = free_cash_flow_quarters(
        series["operating_cash_flow"], series["capex"]
    )
    return series


def actuals[FactT: DatedFact](
    series: Mapping[str, Sequence[Quarter[FactT]]],
    quarter_end: date,
    at: datetime,
    splits: Sequence[Split],
) -> list[Actual[FactT]]:
    """Each actual of the quarter ending on `quarter_end` (series of the facts known at T)."""
    current = _find(series["revenue"], quarter_end) or next(
        (q for m in ("net_income", "operating_cash_flow") if (q := _find(series[m], quarter_end))),
        None,
    )
    if current is None:
        empty = QuarterValue[FactT](
            None, quarter_end, None, f"not reported: the quarter to {quarter_end}"
        )
        return [
            Actual(m, ACTUAL_UNITS[m], empty, empty, empty, None, None, _change_unit(m))
            for m in ACTUAL_UNITS
        ]
    prior_end = current.period_start - timedelta(days=1)
    year_end = current.period_end - timedelta(days=364)
    ends = (current.period_end, prior_end, year_end)

    def value(metric: ActualMetric, end: date, slack: int) -> QuarterValue[FactT]:
        if metric in _MARGIN_PARTS:
            part = _find(series[_MARGIN_PARTS[metric]], end, slack)
            revenue = _find(series["revenue"], end, slack)
            missing = [
                label
                for label, q in (
                    (_MARGIN_PARTS[metric].replace("_", " "), part),
                    ("revenue", revenue),
                )
                if q is None
            ]
            if part is None or revenue is None:
                return QuarterValue(None, end, None, "not reported: " + ", ".join(missing))
            inputs = (_quarter_input(part, at, splits), _quarter_input(revenue, at, splits))
            if revenue.value <= 0:
                return QuarterValue(
                    revenue.period_start,
                    revenue.period_end,
                    None,
                    "revenue is not positive",
                    inputs,
                )
            return QuarterValue(
                revenue.period_start,
                revenue.period_end,
                percent(part.value, revenue.value),
                None,
                inputs,
            )
        found = _find(series[metric], end, slack)
        if found is None:
            reason = (
                "a fourth-quarter EPS is never derived (ADR-013)"
                if metric == "eps_diluted" and _fourth_quarter(series["revenue"], end, slack)
                else f"not reported: {metric.replace('_', ' ')}"
            )
            return QuarterValue(None, end, None, reason)
        quarter_input = _quarter_input(found, at, splits)
        return QuarterValue(
            found.period_start,
            found.period_end,
            quarter_input.value,
            quarter_input.note,
            (quarter_input,),
        )

    out = []
    for metric in ACTUAL_UNITS:
        now, prior, year = (
            value(metric, end, slack) for end, slack in zip(ends, (0, 7, 10), strict=True)
        )
        out.append(
            Actual(
                metric,
                ACTUAL_UNITS[metric],
                now,
                prior,
                year,
                _change(metric, now, prior),
                _change(metric, now, year),
                _change_unit(metric),
            )
        )
    return out


def _fourth_quarter[FactT: DatedFact](
    series: Sequence[Quarter[FactT]], end: date, slack: int
) -> bool:
    found = _find(series, end, slack)
    return found is not None and found.number == 4


def _change_unit(metric: ActualMetric) -> Literal["percent", "percentage points"]:
    return "percentage points" if metric in _MARGIN_PARTS else "percent"


def _change[FactT: DatedFact](
    metric: ActualMetric, now: QuarterValue[FactT], before: QuarterValue[FactT]
) -> Decimal | None:
    if now.value is None or before.value is None:
        return None
    if metric in _MARGIN_PARTS:
        return (now.value - before.value).quantize(RATIO)
    return growth(now.value, before.value) if before.value > 0 else None
