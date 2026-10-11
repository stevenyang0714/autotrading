"""Buyback states and the Buyback Quality Score (M1.4b, ADR-025, errata E7): deterministic,
versioned rules (config/buyback_rules.yaml) over the evidence known at a time T. Pure
functions; no I/O.

States, each requiring the one below it (thresholds are the rule set's):
- WATCH: a new or increased authorization or a yearly plan (B9) announced within
  `announcement_days`, or a remaining authorization stated within them of at least
  `remaining_to_market_cap_min`% of market cap at T.
- ACTIVE: repurchases in the latest reported quarter (ended at most `quarter_max_age_days`
  before T) of at least `quarter_repurchase_to_market_cap_min`% of market cap at the quarter
  end, or any repurchase for a mega cap (market cap then >= `mega_cap_min`, B13), and diluted
  shares of the latest period at most `diluted_shares_change_max`% against a year earlier.
  Market cap at a period end uses the rule set's `period_end_shares` (B12).
- HIGH-CONVICTION candidate: funded by FCF (TTM repurchases at most `repurchase_to_fcf_max` x
  TTM free cash flow, and net debt up by at most `net_debt_increase_max`% of |net debt a year
  earlier|, B7) and valuation context (FCF yield at least `fcf_yield_to_median_min` x its
  month-end median over the last `fcf_yield_history_years`, B10, or a margin of safety to the
  base DCF value of at least `dcf_discount_min`%).
- TRADE-READY: market confirmation (the close above its moving average, or a return above the
  benchmark's) and a passed risk check. The risk check arrives in Phase 2, so this state is
  unreachable in Phase 1 (P1-4); market confirmation is computed and shown.

Each condition is pass, fail or unavailable, with what is missing: missing data never passes.
A level passes when all its conditions pass (WATCH and the valuation context: any of them).
An announcement alone never goes past WATCH, because ACTIVE needs reported repurchases (E7).
No state triggers a trade (02 §5); the thresholds are defaults, not validated (OD-7).

Score (B3, B8, B10): each component maps one measure linearly to 0-100 between two fixed
points, clamped (a mega cap's own 100 point where the rule set gives one, B14); the total is
their weighted mean, unavailable when any component is. It never decides a state.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.buyback import Event, SharesAt, buyback_record, market_cap_at
from autotrading.domain.research import Book, Window, percent, periods
from autotrading.domain.splits import Split, adjust
from autotrading.domain.valuation import (
    NEW_YORK,
    RATIO,
    Close,
    DatedFact,
    Input,
    PriceInput,
    Valued,
    close_basis,
    valuation,
)

Level = Literal["watch", "active", "high_conviction", "trade_ready"]
StateId = Literal["none", "watch", "active", "high_conviction", "trade_ready"]
Status = Literal["pass", "fail", "unavailable"]
Comparison = Literal["at_least", "at_most", "above"]
LEVELS: tuple[Level, ...] = ("watch", "active", "high_conviction", "trade_ready")
SCORE_STEP = Decimal("0.1")
YEAR_DAYS = Decimal("365.25")
KIND_TEXT = {
    "new": "new authorization",
    "increase": "authorization increase",
    "plan": "buyback plan",
    "remaining": "remaining authorization",
}


# ---------- rules (config/buyback_rules.yaml) ----------


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatchRule(_Rule):
    announcement_days: Annotated[int, Field(gt=0)]
    announcement_kinds: list[Literal["new", "increase", "plan"]]
    remaining_to_market_cap_min: Decimal


class ActiveRule(_Rule):
    quarter_repurchase_to_market_cap_min: Decimal
    quarter_max_age_days: Annotated[int, Field(gt=0)]
    diluted_shares_change_max: Decimal
    # B13 (rule 0.2.0): from this market cap at the quarter end (USD), any repurchase in the
    # quarter passes, whatever its share of market cap. None: every company needs the share.
    mega_cap_min: Decimal | None = None


class HighConvictionRule(_Rule):
    repurchase_to_fcf_max: Decimal
    net_debt_increase_max: Decimal
    fcf_yield_to_median_min: Decimal
    fcf_yield_history_years: Annotated[int, Field(gt=0)]
    fcf_yield_history_min_months: Annotated[int, Field(gt=0)]
    dcf_discount_min: Decimal


class TradeReadyRule(_Rule):
    moving_average_sessions: Annotated[int, Field(gt=1)]
    relative_return_sessions: Annotated[int, Field(gt=0)]
    benchmark: str
    reachable: Literal[False]  # the risk check arrives in Phase 2 (P1-4)


class StateRules(_Rule):
    watch: WatchRule
    active: ActiveRule
    high_conviction: HighConvictionRule
    trade_ready: TradeReadyRule


Measure = Literal[
    "fcf_yield_to_median",
    "buyback_intensity",
    "fcf_conversion",
    "net_debt_to_fcf",
    "disciplined_years",
    "net_share_reduction_pct",
]


class ScoreComponentRule(_Rule):
    component: str
    weight: Annotated[int, Field(gt=0)]
    measure: Measure
    zero: Decimal  # the measure scoring 0
    full: Decimal  # the measure scoring 100
    mega_cap_full: Decimal | None = None  # B14: the 100 point of a mega cap, when different

    @model_validator(mode="after")
    def _distinct(self) -> "ScoreComponentRule":
        if self.zero in (self.full, self.mega_cap_full):
            raise ValueError(f"{self.component}: zero and full must differ")
        return self


class ExcludedComponent(_Rule):
    component: str
    weight: Annotated[int, Field(gt=0)]
    reason: str


class DisciplineRule(_Rule):
    years: Annotated[int, Field(gt=0)]
    min_years: Annotated[int, Field(gt=0)]


class ScoreRule(_Rule):
    label: str
    excluded: list[ExcludedComponent]
    components: list[ScoreComponentRule]
    discipline: DisciplineRule
    # B14: market cap at the latest period end (USD) from which `mega_cap_full` applies.
    mega_cap_min: Decimal | None = None


class RuleSet(_Rule):
    """One released rule version: immutable (B4). Settings added after a release have a
    default that keeps the earlier behaviour, and are left out of the content at that default,
    so an earlier version's content and hash stay as released."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    approved: date
    note: str
    # The share count of a period end's market cap (B12): rule 0.1.0 used the balance sheet's.
    period_end_shares: SharesAt = "balance_sheet"
    states: StateRules
    score: ScoreRule

    def content(self) -> dict[str, object]:
        """Everything but a file entry's `status` (retiring a version is not a change to it)
        and settings at the default that predates them."""
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class RuleSetEntry(RuleSet):
    status: Literal["active", "retired"]  # active: evaluated daily

    def rule_set(self) -> RuleSet:
        return RuleSet.model_validate(self.content())


class RulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[RuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "RulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> RuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")

    def get(self, rule_version: str) -> RuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.rule_version == rule_version)


# ---------- evidence and results ----------


@dataclass(frozen=True)
class DcfContext:
    """The base DCF value against the price at T, with the assumption version it used."""

    status: str  # the DCF's own status: ok, unavailable, not_meaningful
    detail: str | None  # why the margin of safety is unavailable
    base_per_share: Decimal | None
    price: Decimal | None
    margin_of_safety: Decimal | None  # percent: (base - price) / base
    assumption_version: int | None  # None: the built-in default


@dataclass(frozen=True)
class Evidence[FactT: DatedFact]:
    """Everything an evaluation at T reads, each as known at T."""

    at: datetime
    facts: Sequence[FactT]
    closes: Sequence[Close]  # raw daily closes, oldest first, back far enough for the record
    splits: Sequence[Split]
    price: PriceInput  # the valuation price at T
    events: Sequence[Event]  # announcements, newest first
    announcements_since: date  # 8-Ks are read from this day on (B2)
    fcf_yield_history: Sequence[tuple[date, Decimal]]  # month ends, each from facts known then
    dcf: DcfContext
    benchmark_closes: Sequence[Close]  # raw daily closes of the benchmark


@dataclass(frozen=True)
class Condition[FactT: DatedFact]:
    condition_id: str  # level.name
    level: Level
    status: Status
    value: Decimal | None  # the measured value, in `unit`
    unit: str  # percent, x, days, USD, percentage points
    threshold: Decimal | None
    comparison: Comparison | None
    detail: str
    inputs: tuple[Input[FactT], ...] = ()
    events: tuple[Event, ...] = ()


@dataclass(frozen=True)
class LevelResult:
    level: Level
    status: Status
    rule: str  # how its conditions combine


@dataclass(frozen=True)
class Component[FactT: DatedFact]:
    component: str
    weight: int
    measure: Measure
    zero: Decimal
    full: Decimal
    value: Decimal | None  # the measure
    score: Decimal | None  # 0-100
    detail: str | None  # why it is unavailable, or how it was measured
    inputs: tuple[Input[FactT], ...] = ()


@dataclass(frozen=True)
class Score[FactT: DatedFact]:
    total: Decimal | None  # 0-100
    detail: str | None
    label: str
    components: list[Component[FactT]]


@dataclass(frozen=True)
class Assessment[FactT: DatedFact]:
    state: StateId
    levels: list[LevelResult]
    conditions: list[Condition[FactT]]
    score: Score[FactT]
    period: Window | None  # the latest period the conditions and score read


def _all(statuses: Sequence[Status]) -> Status:
    if "fail" in statuses:
        return "fail"
    return "pass" if all(s == "pass" for s in statuses) else "unavailable"


def _any(statuses: Sequence[Status]) -> Status:
    if "pass" in statuses:
        return "pass"
    return "fail" if all(s == "fail" for s in statuses) else "unavailable"


def _compare(value: Decimal, threshold: Decimal, comparison: Comparison) -> Status:
    met = {
        "at_least": value >= threshold,
        "at_most": value <= threshold,
        "above": value > threshold,
    }[comparison]
    return "pass" if met else "fail"


def _day(at: datetime) -> date:
    return at.astimezone(NEW_YORK).date()


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(RATIO)


def _billions(amount: Decimal) -> str:
    return f"${(amount / 10**9).normalize():f} billion"


def _missing(*named: tuple[str, object]) -> str:
    return "not reported: " + ", ".join(label for label, value in named if value is None)


def median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# ---------- WATCH ----------


def _stated_remaining(event: Event) -> Decimal | None:
    return event.amount if event.kind == "remaining" else event.remaining_amount


def _watch[FactT: DatedFact](
    rule: WatchRule, ev: Evidence[FactT], cap: Valued[FactT]
) -> list[Condition[FactT]]:
    day = _day(ev.at)
    since = day - timedelta(days=rule.announcement_days)
    in_window = [e for e in ev.events if since <= e.day <= day]
    partial = since < ev.announcements_since
    coverage = f"8-Ks are read from {ev.announcements_since} only"
    window = Decimal(rule.announcement_days)

    announced = [e for e in in_window if e.kind in rule.announcement_kinds]
    if announced:
        latest = max(announced, key=lambda e: (e.day, e.first_published_at))
        announcement = Condition[FactT](
            "watch.announcement",
            "watch",
            "pass",
            Decimal((day - latest.day).days),
            "days",
            window,
            "at_most",
            f"{KIND_TEXT[latest.kind]} announced {latest.day}",
            events=(latest,),
        )
    else:
        announcement = Condition[FactT](
            "watch.announcement",
            "watch",
            "unavailable" if partial else "fail",
            None,
            "days",
            window,
            "at_most",
            f"none since {since}" + (f"; {coverage}" if partial else ""),
        )

    stated = [e for e in in_window if _stated_remaining(e) is not None]
    threshold = rule.remaining_to_market_cap_min
    if not stated:
        remaining = Condition[FactT](
            "watch.remaining",
            "watch",
            "unavailable" if partial else "fail",
            None,
            "percent",
            threshold,
            "at_least",
            f"no remaining authorization stated since {since}"
            + (f"; {coverage}" if partial else ""),
        )
    else:
        latest = max(stated, key=lambda e: (e.day, e.first_published_at))
        amount = _stated_remaining(latest)
        assert amount is not None
        if cap.value is None:
            remaining = Condition[FactT](
                "watch.remaining",
                "watch",
                "unavailable",
                None,
                "percent",
                threshold,
                "at_least",
                f"market cap: {cap.detail}",
                events=(latest,),
            )
        else:
            share = percent(amount, cap.value)
            remaining = Condition[FactT](
                "watch.remaining",
                "watch",
                _compare(share, threshold, "at_least"),
                share,
                "percent",
                threshold,
                "at_least",
                f"remaining authorization stated {latest.day} / market cap at T",
                inputs=tuple(cap.inputs),
                events=(latest,),
            )
    return [announcement, remaining]


# ---------- ACTIVE ----------


def _active[FactT: DatedFact](
    rule: ActiveRule,
    ev: Evidence[FactT],
    book: Book[FactT],
    latest: dict[str, Valued[FactT]],
    shares_at: SharesAt,
) -> list[Condition[FactT]]:
    day = _day(ev.at)
    threshold = rule.quarter_repurchase_to_market_cap_min
    quarters = [q for q in book.series("share_repurchases") if q.period_end <= day]
    if not quarters:
        quarter = Condition[FactT](
            "active.quarter_repurchase",
            "active",
            "unavailable",
            None,
            "percent",
            threshold,
            "at_least",
            "not reported: share repurchases",
        )
    else:
        q = max(quarters, key=lambda q: q.period_end)
        paid = Input[FactT](
            "share_repurchases_quarter",
            q.value,
            q.period_start,
            q.period_end,
            q.inputs,
            None if q.method == "reported" else q.method.replace("_", " "),
        )
        age = (day - q.period_end).days

        def condition(
            status: Status, value: Decimal | None, detail: str, *extra: Input[FactT]
        ) -> Condition[FactT]:
            return Condition(
                "active.quarter_repurchase",
                "active",
                status,
                value,
                "percent",
                threshold,
                "at_least",
                detail,
                inputs=(paid, *extra),
            )

        if age > rule.quarter_max_age_days:
            quarter = condition(
                "fail",
                None,
                f"the latest reported quarter ended {q.period_end}, more than "
                f"{rule.quarter_max_age_days} days before",
            )
        elif q.value <= 0:
            quarter = condition("fail", None, f"no repurchases in the quarter ended {q.period_end}")
        else:
            cap, missing = market_cap_at(book, ev.closes, q.period_end, shares_at)
            if cap is None or cap.value is None:
                quarter = condition("unavailable", None, "not reported: " + ", ".join(missing))
            elif rule.mega_cap_min is not None and cap.value >= rule.mega_cap_min:
                # B13: a mega cap passes on any repurchase in the quarter (checked above).
                quarter = Condition(
                    "active.quarter_repurchase",
                    "active",
                    "pass",
                    percent(q.value, cap.value),
                    "percent",
                    Decimal(0),
                    "above",
                    f"mega cap (market cap at the quarter end >= {_billions(rule.mega_cap_min)}): "
                    f"any repurchase counts; repurchases in the quarter ended {q.period_end} / "
                    "market cap then",
                    inputs=(paid, cap),
                )
            else:
                share = percent(q.value, cap.value)
                quarter = condition(
                    _compare(share, threshold, "at_least"),
                    share,
                    f"repurchases in the quarter ended {q.period_end} / market cap then",
                    cap,
                )

    change = latest.get("diluted_shares_change")
    limit = rule.diluted_shares_change_max
    if change is None or change.value is None:
        shares = Condition[FactT](
            "active.diluted_shares",
            "active",
            "unavailable",
            None,
            "percent",
            limit,
            "at_most",
            change.detail if change and change.detail else "no reported period",
            inputs=tuple(change.inputs) if change else (),
        )
    else:
        shares = Condition[FactT](
            "active.diluted_shares",
            "active",
            _compare(change.value, limit, "at_most"),
            change.value,
            "percent",
            limit,
            "at_most",
            change.detail or "diluted shares against a year earlier",
            inputs=tuple(change.inputs),
        )
    return [quarter, shares]


# ---------- HIGH-CONVICTION ----------


@dataclass(frozen=True)
class _YieldRatio[FactT: DatedFact]:
    value: Decimal | None
    detail: str
    inputs: tuple[Input[FactT], ...]


def _fcf_yield_ratio[FactT: DatedFact](
    rule: HighConvictionRule, ev: Evidence[FactT], current: Valued[FactT]
) -> _YieldRatio[FactT]:
    """FCF yield at T / its month-end median over the last `fcf_yield_history_years` (B10)."""
    day = _day(ev.at)
    since = day - timedelta(days=int(YEAR_DAYS * rule.fcf_yield_history_years))
    history = [v for d, v in ev.fcf_yield_history if since < d <= day]
    if current.value is None:
        return _YieldRatio(None, f"FCF yield: {current.detail}", tuple(current.inputs))
    if len(history) < rule.fcf_yield_history_min_months:
        return _YieldRatio(
            None,
            f"FCF yield known at {len(history)} month ends since {since}; "
            f"{rule.fcf_yield_history_min_months} needed",
            tuple(current.inputs),
        )
    middle = median(history).quantize(RATIO)
    found = Input[FactT](
        "fcf_yield_median",
        middle,
        since,
        day,
        (),
        f"median of {len(history)} month ends, each from the facts and close known then",
    )
    now = Input[FactT]("fcf_yield", current.value, None, day, (), "FCF yield at T")
    inputs = (now, found, *current.inputs)
    if middle <= 0:
        return _YieldRatio(None, "the median FCF yield is not positive", inputs)
    return _YieldRatio(
        _ratio(current.value, middle), "FCF yield at T / its month-end median", inputs
    )


def _high_conviction[FactT: DatedFact](
    rule: HighConvictionRule,
    ev: Evidence[FactT],
    book: Book[FactT],
    window: Window | None,
    yield_ratio: _YieldRatio[FactT],
) -> list[Condition[FactT]]:
    out: list[Condition[FactT]] = []
    limit = rule.repurchase_to_fcf_max
    if window is None:
        out.append(
            Condition(
                "high_conviction.fcf_funding",
                "high_conviction",
                "unavailable",
                None,
                "x",
                limit,
                "at_most",
                "no reported period",
            )
        )
    else:
        paid = book.flow("share_repurchases", window)
        fcf, fcf_missing = book.free_cash_flow(window)
        inputs = tuple(i for i in (paid, fcf) if i is not None)
        if paid is None or fcf is None or paid.value is None or fcf.value is None:
            absent = (["share repurchases"] if paid is None else []) + (
                fcf_missing if fcf is None else []
            )
            out.append(
                Condition(
                    "high_conviction.fcf_funding",
                    "high_conviction",
                    "unavailable",
                    None,
                    "x",
                    limit,
                    "at_most",
                    "not reported: " + ", ".join(absent),
                    inputs,
                )
            )
        elif fcf.value <= 0:
            out.append(
                Condition(
                    "high_conviction.fcf_funding",
                    "high_conviction",
                    "pass" if paid.value <= 0 else "fail",
                    None,
                    "x",
                    limit,
                    "at_most",
                    "free cash flow is not positive",
                    inputs,
                )
            )
        else:
            ratio = _ratio(paid.value, fcf.value)
            out.append(
                Condition(
                    "high_conviction.fcf_funding",
                    "high_conviction",
                    _compare(ratio, limit, "at_most"),
                    ratio,
                    "x",
                    limit,
                    "at_most",
                    "repurchases / free cash flow of the latest period",
                    inputs,
                )
            )

    limit = rule.net_debt_increase_max
    before = book.net_debt(window.opening) if window else None
    after = book.net_debt(window.end) if window else None
    if window is None or before is None or after is None:
        out.append(
            Condition(
                "high_conviction.net_debt",
                "high_conviction",
                "unavailable",
                None,
                "percent",
                limit,
                "at_most",
                "no reported period"
                if window is None
                else _missing(
                    (f"net debt on {window.opening}", before), (f"net debt on {window.end}", after)
                ),
                tuple(i for i in (before, after) if i is not None),
            )
        )
    else:
        assert before.value is not None and after.value is not None
        rise = after.value - before.value
        if before.value == 0:
            status: Status = "pass" if rise <= 0 else "fail"
            value, detail = None, "net debt a year earlier was 0"
        else:
            value = percent(rise, abs(before.value))
            status = _compare(value, limit, "at_most")
            detail = "net debt change / |net debt a year earlier|"
        out.append(
            Condition(
                "high_conviction.net_debt",
                "high_conviction",
                status,
                value,
                "percent",
                limit,
                "at_most",
                detail,
                (before, after),
            )
        )

    limit = rule.fcf_yield_to_median_min
    out.append(
        Condition(
            "high_conviction.fcf_yield",
            "high_conviction",
            "unavailable"
            if yield_ratio.value is None
            else _compare(yield_ratio.value, limit, "at_least"),
            yield_ratio.value,
            "x",
            limit,
            "at_least",
            yield_ratio.detail,
            yield_ratio.inputs,
        )
    )

    limit = rule.dcf_discount_min
    dcf = ev.dcf
    version = (
        f"assumption version {dcf.assumption_version}"
        if dcf.assumption_version is not None
        else "the built-in default assumptions"
    )
    dcf_inputs: tuple[Input[FactT], ...] = tuple(
        Input(name, value, None, _day(ev.at), (), note)
        for name, value, note in (
            ("fair_value_dcf", dcf.base_per_share, f"base scenario, {version}"),
            ("price", dcf.price, "end-of-day close"),
        )
        if value is not None
    )
    out.append(
        Condition(
            "high_conviction.dcf_discount",
            "high_conviction",
            "unavailable"
            if dcf.margin_of_safety is None
            else _compare(dcf.margin_of_safety, limit, "at_least"),
            dcf.margin_of_safety,
            "percent",
            limit,
            "at_least",
            f"margin of safety to the base DCF value, {version}"
            if dcf.margin_of_safety is not None
            else dcf.detail or "no DCF value",
            dcf_inputs,
        )
    )
    return out


# ---------- TRADE-READY ----------


def _adjusted_closes(closes: Sequence[Close], at: datetime, splits: Sequence[Split]) -> list[Close]:
    """End-of-day closes public at T, each on T's split basis, oldest first."""
    out = []
    for close in sorted(closes, key=lambda c: c.day):
        if close.feed_status != "end_of_day" or close.published_at > at:
            continue
        moved = adjust("close", close.close, close_basis(close), at, splits)
        out.append(
            Close(
                close.day, moved.value if moved else close.close, "end_of_day", close.published_at
            )
        )
    return out


def _trade_ready[FactT: DatedFact](
    rule: TradeReadyRule, ev: Evidence[FactT]
) -> list[Condition[FactT]]:
    closes = _adjusted_closes(ev.closes, ev.at, ev.splits)
    usable = ev.price.status == "ok" and ev.price.close is not None
    zero = Decimal(0)
    n = rule.moving_average_sessions
    if not usable or len(closes) < n:
        average = Condition[FactT](
            "trade_ready.above_average",
            "trade_ready",
            "unavailable",
            None,
            "percent",
            zero,
            "above",
            f"no valuation price: {ev.price.detail}"
            if not usable
            else f"{len(closes)} end-of-day closes; {n} needed",
        )
    else:
        last = closes[-n:]
        mean = sum((c.close for c in last), Decimal(0)) / n
        gap = ((last[-1].close / mean - 1) * 100).quantize(RATIO)
        average = Condition[FactT](
            "trade_ready.above_average",
            "trade_ready",
            _compare(gap, zero, "above"),
            gap,
            "percent",
            zero,
            "above",
            f"close {last[-1].day} against its {n}-session average",
            (
                Input("price", last[-1].close, None, last[-1].day, (), "end-of-day close"),
                Input(
                    "moving_average",
                    mean.quantize(Decimal("0.0001")),
                    last[0].day,
                    last[-1].day,
                    (),
                    f"mean of {n} end-of-day closes, split-adjusted",
                ),
            ),
        )

    k = rule.relative_return_sessions
    benchmark = [
        c
        for c in sorted(ev.benchmark_closes, key=lambda c: c.day)
        if c.feed_status == "end_of_day" and c.published_at <= ev.at
    ]
    if not usable or len(closes) <= k:
        relative = Condition[FactT](
            "trade_ready.relative_return",
            "trade_ready",
            "unavailable",
            None,
            "percentage points",
            zero,
            "above",
            f"no valuation price: {ev.price.detail}"
            if not usable
            else f"{len(closes)} end-of-day closes; {k + 1} needed",
        )
    else:
        start, end = closes[-k - 1], closes[-1]
        base = next((c for c in reversed(benchmark) if c.day <= start.day), None)
        top = next((c for c in reversed(benchmark) if c.day <= end.day), None)
        if base is None or top is None or base.day < start.day - timedelta(days=7):
            relative = Condition[FactT](
                "trade_ready.relative_return",
                "trade_ready",
                "unavailable",
                None,
                "percentage points",
                zero,
                "above",
                f"not reported: {rule.benchmark} end-of-day close on {start.day}",
            )
        else:
            own = (end.close / start.close - 1) * 100
            theirs = (top.close / base.close - 1) * 100
            spread = (own - theirs).quantize(RATIO)
            relative = Condition[FactT](
                "trade_ready.relative_return",
                "trade_ready",
                _compare(spread, zero, "above"),
                spread,
                "percentage points",
                zero,
                "above",
                f"return {start.day} to {end.day} minus {rule.benchmark}'s",
                (
                    Input("return", own.quantize(RATIO), start.day, end.day, (), "split-adjusted"),
                    Input(
                        "benchmark_return",
                        theirs.quantize(RATIO),
                        base.day,
                        top.day,
                        (),
                        rule.benchmark,
                    ),
                ),
            )

    risk = Condition[FactT](
        "trade_ready.risk_check",
        "trade_ready",
        "unavailable",
        None,
        "",
        None,
        None,
        "the risk check arrives in Phase 2: TRADE-READY is unreachable in Phase 1",
    )
    return [average, relative, risk]


# ---------- score ----------


def linear(value: Decimal, zero: Decimal, full: Decimal) -> Decimal:
    """0 at `zero`, 100 at `full`, linear between and clamped outside."""
    fraction = (value - zero) / (full - zero)
    return (min(max(fraction, Decimal(0)), Decimal(1)) * 100).quantize(SCORE_STEP)


def _measures[FactT: DatedFact](
    rule: ScoreRule,
    book: Book[FactT],
    window: Window | None,
    latest: dict[str, Valued[FactT]],
    years: list[dict[str, Valued[FactT]]],
    yield_ratio: _YieldRatio[FactT],
) -> dict[Measure, tuple[Decimal | None, str | None, tuple[Input[FactT], ...]]]:
    def from_record(metric: str) -> tuple[Decimal | None, str | None, tuple[Input[FactT], ...]]:
        found = latest.get(metric)
        if found is None:
            return None, "no reported period", ()
        return found.value, found.detail, tuple(found.inputs)

    out: dict[Measure, tuple[Decimal | None, str | None, tuple[Input[FactT], ...]]] = {
        "fcf_yield_to_median": (yield_ratio.value, yield_ratio.detail, yield_ratio.inputs),
        "buyback_intensity": from_record("buyback_intensity"),
        "net_share_reduction_pct": from_record("net_share_reduction_pct"),
    }

    if window is None:
        out["fcf_conversion"] = out["net_debt_to_fcf"] = (None, "no reported period", ())
    else:
        fcf, fcf_missing = book.free_cash_flow(window)
        fcf_absent = "not reported: " + ", ".join(fcf_missing)
        income = book.flow("net_income", window)
        debt = book.net_debt(window.end)
        out["fcf_conversion"] = _quotient(
            (fcf, fcf_absent), (income, "not reported: net income"), "net income", percent
        )
        out["net_debt_to_fcf"] = _quotient(
            (debt, f"not reported: net debt on {window.end}"),
            (fcf, fcf_absent),
            "free cash flow",
            _ratio,
        )

    known: list[bool] = []
    inputs: list[Input[FactT]] = []
    for values in years[: rule.discipline.years]:
        paid, funded, reduction = (
            values[m] for m in ("share_repurchases", "repurchase_to_fcf", "net_share_reduction")
        )
        if paid.value is None or reduction.value is None:
            continue
        if funded.value is not None:
            within = funded.value <= 100
        elif funded.reason == "not_meaningful":  # free cash flow not positive
            within = paid.value <= 0
        else:
            continue
        known.append(within and reduction.value > 0)
        inputs += [*funded.inputs, *reduction.inputs]
    if len(known) < rule.discipline.min_years:
        out["disciplined_years"] = (
            None,
            f"{len(known)} fiscal years with repurchases, free cash flow and share counts; "
            f"{rule.discipline.min_years} needed",
            (),
        )
    else:
        out["disciplined_years"] = (
            percent(Decimal(sum(known)), Decimal(len(known))),
            f"{sum(known)} of {len(known)} fiscal years: repurchases within free cash flow "
            "and fewer shares outstanding",
            tuple(dict.fromkeys(inputs)),
        )
    return out


def _quotient[FactT: DatedFact](
    numerator: tuple[Input[FactT] | None, str],
    denominator: tuple[Input[FactT] | None, str],
    label: str,
    scale: Callable[[Decimal, Decimal], Decimal],
) -> tuple[Decimal | None, str | None, tuple[Input[FactT], ...]]:
    """numerator / a positive denominator, or why not (each part: the input, its absence)."""
    (top, top_absent), (bottom, bottom_absent) = numerator, denominator
    inputs = tuple(i for i in (top, bottom) if i is not None)
    if top is None or top.value is None:
        return None, top_absent, inputs
    if bottom is None or bottom.value is None:
        return None, bottom_absent, inputs
    if bottom.value <= 0:
        return None, f"{label} is not positive", inputs
    return scale(top.value, bottom.value), None, inputs


def _mega_cap[FactT: DatedFact](
    inputs: Sequence[Input[FactT]], minimum: Decimal | None
) -> Decimal | None:
    """The market cap among a measure's inputs when it is at least `minimum` (B14)."""
    cap = next((i.value for i in inputs if i.name == "market_cap"), None)
    return cap if minimum is not None and cap is not None and cap >= minimum else None


def _score[FactT: DatedFact](
    rule: ScoreRule,
    measures: dict[Measure, tuple[Decimal | None, str | None, tuple[Input[FactT], ...]]],
) -> Score[FactT]:
    components: list[Component[FactT]] = []
    for c in rule.components:
        value, detail, inputs = measures[c.measure]
        full = c.full
        if c.mega_cap_full is not None and _mega_cap(inputs, rule.mega_cap_min) is not None:
            assert rule.mega_cap_min is not None
            full = c.mega_cap_full
            detail = "; ".join(
                part
                for part in (
                    detail,
                    f"mega cap (market cap >= {_billions(rule.mega_cap_min)}): 100 at {full}",
                )
                if part
            )
        components.append(
            Component(
                c.component,
                c.weight,
                c.measure,
                c.zero,
                full,
                value,
                linear(value, c.zero, full) if value is not None else None,
                detail,
                inputs,
            )
        )
    missing = [c.component.replace("_", " ") for c in components if c.score is None]
    if missing:
        return Score(None, "unavailable: " + ", ".join(missing), rule.label, components)
    weight = sum(c.weight for c in components)
    total = sum((c.score * c.weight for c in components if c.score is not None), Decimal(0))
    return Score((total / weight).quantize(SCORE_STEP), None, rule.label, components)


# ---------- the assessment ----------


def assess[FactT: DatedFact](rules: RuleSet, ev: Evidence[FactT]) -> Assessment[FactT]:
    """The state, its conditions and the score at T under one rule set."""
    book = Book(ev.facts, ev.at, ev.splits)
    record = buyback_record(ev.facts, ev.closes, ev.at, ev.splits, rules.period_end_shares)
    shown = periods(book)
    by_period = [
        {metric: values[i] for _, metric, _, values in record.rows} for i in range(len(shown))
    ]
    window = shown[0] if shown else None
    latest = by_period[0] if by_period else {}
    years = [v for w, v in zip(shown, by_period, strict=True) if w.kind == "fiscal_year"]
    at_t = {v.metric_id: v for v in valuation(ev.facts, ev.price, ev.splits)}
    yield_ratio = _fcf_yield_ratio(rules.states.high_conviction, ev, at_t["fcf_yield"])

    watch = _watch(rules.states.watch, ev, at_t["market_cap"])
    active = _active(rules.states.active, ev, book, latest, rules.period_end_shares)
    conviction = _high_conviction(rules.states.high_conviction, ev, book, window, yield_ratio)
    ready = _trade_ready(rules.states.trade_ready, ev)
    status = {c.condition_id: c.status for c in (*watch, *active, *conviction, *ready)}
    levels = [
        LevelResult("watch", _any([c.status for c in watch]), "any condition"),
        LevelResult("active", _all([c.status for c in active]), "every condition"),
        LevelResult(
            "high_conviction",
            _all(
                [
                    status["high_conviction.fcf_funding"],
                    status["high_conviction.net_debt"],
                    _any(
                        [
                            status["high_conviction.fcf_yield"],
                            status["high_conviction.dcf_discount"],
                        ]
                    ),
                ]
            ),
            "FCF funding and net debt, and FCF yield or DCF discount",
        ),
        LevelResult(
            "trade_ready",
            _all(
                [
                    _any(
                        [
                            status["trade_ready.above_average"],
                            status["trade_ready.relative_return"],
                        ]
                    ),
                    status["trade_ready.risk_check"],
                ]
            ),
            "market confirmation (either) and the risk check",
        ),
    ]
    state: StateId = "none"
    for result in levels:
        if result.status != "pass":
            break
        state = result.level
    if state == "trade_ready" or rules.states.trade_ready.reachable:  # P1-4, never in Phase 1
        raise AssertionError("TRADE-READY is unreachable in Phase 1")
    measures = _measures(rules.score, book, window, latest, years, yield_ratio)
    return Assessment(
        state,
        levels,
        [*watch, *active, *conviction, *ready],
        _score(rules.score, measures),
        window,
    )
