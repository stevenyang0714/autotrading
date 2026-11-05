"""Taiwan listed-stock screens (M3.11, ADR-042). Pure; no I/O.

Steven's workflow (2026-10-26): explicit conditions, checked every session over every listed
company, and the names that meet them in a research report; nothing judged when the data is
incomplete or not updated; the conditions checked against history so they are not too wide.
A research screen and a watch list, not a buy or sell signal; the conditions are unvalidated
(no forward returns, OD-7).

- Each stock is read from its own bars in the last `window_sessions` market sessions (SC10).
  Its return across an ex-date comes from the session's reference price (SC6). Neither file
  gives it: TWSE and FinMind both state a change of 0 on an ex-date (checked on the recorded
  files). So it is FinMind's ex-dividend results' reference price where there is one (the
  history), else the previous close less the cash dividend over one plus the stock dividend
  that TWSE's TWT48U_ALL announced (from M3.11 on), else the previous close; a session with a
  change of 0 and a different close and no recorded action is an `unexplained` gap (a capital
  reduction, say). Prices are put on T's basis by chaining the returns back from T's close, so
  an ex-dividend drop is not a fall.
- Movers (SC7): how much a liquid stock moved against its own volatility (z) or its own volume
  (volume ratio), ordered across stocks by that change (SC14, Steven 2026-11-04).
- Screens (SC8): required conditions; notes shown but not required (institutional flows,
  fetched for candidates only); the conditions that end a stock's watch (SC9). Industry
  breadth is the share of an industry's liquid stocks above their own average (SC14).

Arithmetic is binary floating point (IEEE 754: +, -, *, / and sqrt are correctly rounded, so a
window always gives the same result), each value stored rounded to 4 decimals; every reading
depends on the stock's window only, so a scheduled run, a backfill and a recompute agree.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Q4 = Decimal("0.0001")
Status = Literal["pass", "fail", "unavailable", "not_applicable"]
State = Literal["entered", "on_watch", "invalidated", "expired"]
Investor = Literal["foreign", "trust"]
INVESTORS_ZH = {"foreign": "外資", "trust": "投信"}
EPSILON = 1e-9


def _q(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(value).quantize(Q4)


def _twd(amount: Decimal) -> str:
    """NT$ in 萬 when whole (30000000 -> 'NT$3,000 萬')."""
    if amount % 10000 == 0:
        return f"NT${int(amount / 10000):,} 萬"
    return f"NT${amount:,}"


def _pct(share: Decimal) -> str:
    return f"{(share * 100).normalize():f}%"


# ---------- rules ----------


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Sessions = Annotated[int, Field(gt=1, le=250)]


class Liquid(_Rule):
    """The liquidity of the rule set (sessions, minimum average trade value, history)."""

    kind: Literal["liquid"]

    def label(self, rules: "ScreenRuleSet") -> str:
        return (
            f"{rules.liquidity.sessions} 日平均成交值 ≥ "
            f"{_twd(rules.liquidity.min_avg_trade_value_twd)}"
        )


class CloseAboveSma(_Rule):
    kind: Literal["close_above_sma"]
    sessions: Sessions

    def label(self, rules: "ScreenRuleSet") -> str:
        return f"收盤價高於 {self.sessions} 日均線"


class SmaRising(_Rule):
    kind: Literal["sma_rising"]
    sessions: Sessions
    lookback: Annotated[int, Field(gt=0, le=60)]

    def label(self, rules: "ScreenRuleSet") -> str:
        return f"{self.sessions} 日均線高於 {self.lookback} 日前"


class RangeWidthMax(_Rule):
    kind: Literal["range_width_max"]
    sessions: Sessions
    percent: Annotated[Decimal, Field(gt=0, le=100)]

    def label(self, rules: "ScreenRuleSet") -> str:
        return f"前 {self.sessions} 日高低區間 ≤ {self.percent}%"


class CloseAboveRangeHigh(_Rule):
    kind: Literal["close_above_range_high"]
    sessions: Sessions

    def label(self, rules: "ScreenRuleSet") -> str:
        return f"收盤價突破前 {self.sessions} 日最高價"


class VolumeMultipleMin(_Rule):
    kind: Literal["volume_multiple_min"]
    sessions: Sessions
    multiple: Annotated[Decimal, Field(gt=0)]

    def label(self, rules: "ScreenRuleSet") -> str:
        return f"成交量 ≥ 前 {self.sessions} 日均量 {self.multiple} 倍"


class IndustryBreadthMin(_Rule):
    kind: Literal["industry_breadth_min"]
    sessions: Sessions
    share: Annotated[Decimal, Field(gt=0, le=1)]
    min_members: Annotated[int, Field(gt=1)]

    def label(self, rules: "ScreenRuleSet") -> str:
        return (
            f"同產業有流動性的股票中 ≥ {_pct(self.share)} 站上 {self.sessions} 日均線"
            f"（≥ {self.min_members} 檔才判斷）"
        )


Condition = Annotated[
    Liquid
    | CloseAboveSma
    | SmaRising
    | RangeWidthMax
    | CloseAboveRangeHigh
    | VolumeMultipleMin
    | IndustryBreadthMin,
    Field(discriminator="kind"),
]


class ClosesBelowSma(_Rule):
    kind: Literal["closes_below_sma"]
    sessions: Sessions
    consecutive: Annotated[int, Field(gt=0, le=10)]

    def label(self) -> str:
        return f"連續 {self.consecutive} 日收盤低於 {self.sessions} 日均線"


class CloseBelowLevel(_Rule):
    """The close falls back below the level recorded at entry: the range high the stock broke
    (the screen's close_above_range_high condition), moved to each later session's basis."""

    kind: Literal["close_below_level"]

    def label(self) -> str:
        return "收盤跌回突破價之下"


Invalidation = Annotated[ClosesBelowSma | CloseBelowLevel, Field(discriminator="kind")]


class FlowNetBuy(_Rule):
    kind: Literal["flow_net_buy"]
    investor: Investor
    sessions: Annotated[int, Field(gt=0, le=20)]
    min_days: Annotated[int, Field(gt=0)]

    def label(self) -> str:
        return f"{INVESTORS_ZH[self.investor]}近 {self.sessions} 日至少 {self.min_days} 日買超"


class Screen(_Rule):
    screen_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    name_zh: Annotated[str, Field(min_length=1, max_length=20)]
    conditions: Annotated[list[Condition], Field(min_length=1)]
    notes: list[FlowNetBuy] = []
    invalidation: Annotated[list[Invalidation], Field(min_length=1)]

    @model_validator(mode="after")
    def _level(self) -> "Screen":
        if any(isinstance(i, CloseBelowLevel) for i in self.invalidation) and not any(
            isinstance(c, CloseAboveRangeHigh) for c in self.conditions
        ):
            raise ValueError("close_below_level needs a close_above_range_high condition")
        return self

    def level_sessions(self) -> int | None:
        return next(
            (c.sessions for c in self.conditions if isinstance(c, CloseAboveRangeHigh)), None
        )


class Readiness(_Rule):
    min_coverage: Annotated[Decimal, Field(gt=0, le=1)]
    lookback_sessions: Annotated[int, Field(gt=0, le=20)]
    # 0.2.0: of the companies with a bar at T, the share with `min_history` sessions (a history
    # still being backfilled is not a quiet market); None in 0.1.0
    min_history_share: Annotated[Decimal, Field(gt=0, le=1)] | None = None


class Liquidity(_Rule):
    sessions: Sessions
    min_avg_trade_value_twd: Annotated[Decimal, Field(ge=0)]
    min_history: Sessions


class MoverRules(_Rule):
    volatility_sessions: Sessions
    z_threshold: Annotated[Decimal, Field(gt=0)]
    change_sessions: Annotated[int, Field(gt=1, le=20)]
    volume_sessions: Sessions
    volume_ratio: Annotated[Decimal, Field(gt=1)]
    page_top: Annotated[int, Field(gt=0, le=100)]
    push_top: Annotated[int, Field(gt=0, le=30)]


class FlowRules(_Rule):
    max_requests: Annotated[int, Field(gt=0, le=300)]


class ScreenRuleSet(_Rule):
    """One released rule version: immutable (a change is a new version)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    market: Literal["TW"]
    exclude_industries: list[Annotated[str, Field(pattern=r"^\d{2}$")]]
    window_sessions: Annotated[int, Field(gt=1, le=250)]
    readiness: Readiness
    liquidity: Liquidity
    movers: MoverRules
    watch_sessions: Annotated[int, Field(gt=0, le=120)]
    action_flag_ratio: Annotated[Decimal, Field(gt=0, lt=1)]
    flows: FlowRules
    screens: Annotated[list[Screen], Field(min_length=1)]

    @model_validator(mode="after")
    def _consistent(self) -> "ScreenRuleSet":
        ids = [s.screen_id for s in self.screens]
        if len(ids) != len(set(ids)):
            raise ValueError("a screen_id is used twice")
        needed = max(
            self.liquidity.min_history,
            self.movers.volatility_sessions + 1,
            self.movers.volume_sessions + 1,
            *(_needed(c) for s in self.screens for c in s.conditions),
        )
        if self.window_sessions < needed:
            raise ValueError(f"window_sessions {self.window_sessions} < {needed} needed")
        if self.liquidity.min_history < needed - 1:
            raise ValueError(f"min_history {self.liquidity.min_history} < {needed - 1} needed")
        return self

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def _needed(condition: Condition) -> int:
    """Sessions of bars a condition reads, T included."""
    if isinstance(condition, SmaRising):
        return condition.sessions + condition.lookback
    if isinstance(condition, RangeWidthMax | CloseAboveRangeHigh | VolumeMultipleMin):
        return condition.sessions + 1
    if isinstance(condition, CloseAboveSma | IndustryBreadthMin):
        return condition.sessions + 1  # +1: closes_below_sma reads the session before too
    return 1


class ScreenRuleSetEntry(ScreenRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> ScreenRuleSet:
        return ScreenRuleSet.model_validate(self.content())


class ScreenRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[ScreenRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "ScreenRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> ScreenRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


def describe(rules: ScreenRuleSet, screen: Screen) -> dict[str, list[str]]:
    """The screen in words, from its rules: conditions, notes and what ends a watch."""
    return {
        "conditions": [c.label(rules) for c in screen.conditions],
        "notes": [n.label() for n in screen.notes],
        "invalidation": [i.label() for i in screen.invalidation]
        + [f"觀察滿 {rules.watch_sessions} 個交易日且不再符合條件"],
    }


# ---------- inputs ----------


@dataclass(frozen=True)
class DailyBar:
    """One stored raw bar and the session's measures, as known at T (floats for arithmetic,
    `close_text` the stored close exactly)."""

    session: date
    open: float
    high: float
    low: float
    close: float
    close_text: str
    volume: float  # shares
    trade_value: float | None  # TWD
    change: float | None  # the stored price change
    reference: float | None  # the ex-date's reference price (FinMind ex-dividend results)
    cash: float | None  # a cash dividend going ex this session (TWD a share)
    stock_ratio: float | None  # a stock dividend going ex: new shares per share
    feed: str  # twse or finmind
    feed_status: str  # end_of_day, or fixture for recorded test data (the DEMO banner)
    row_id: str
    published_at: datetime


@dataclass(frozen=True)
class Company:
    code: str
    name: str
    industry: str


@dataclass(frozen=True)
class Flow:
    """Net buying of one session, in shares (FinMind, ADR-040 TW23)."""

    session: date
    foreign: float
    trust: float


@dataclass(frozen=True)
class Watched:
    """A stock on a screen's watch list after a judged run: it stays until a condition of the
    screen's `invalidation` ends it, or until it has been on the list `watch_sessions` judged
    sessions and no longer meets the screen (SC9)."""

    code: str
    entered: date
    sessions: int  # judged sessions on the list, the entry included
    level: Decimal | None  # close_below_level's level on that run's basis


@dataclass(frozen=True)
class PreviousRun:
    session: date
    watch: Mapping[str, Sequence[Watched]]  # screen_id -> its list


# ---------- one stock's window ----------


@dataclass(frozen=True)
class Event:
    session: date
    factor: float  # reference / previous close; 1 when unknown
    source: Literal["ex_reference", "dividend", "gap", "unexplained"]


@dataclass(frozen=True)
class Window:
    bars: tuple[DailyBar, ...]  # oldest first; the last is T
    returns: tuple[float, ...]  # returns[i]: bars[i + 1] over bars[i]
    levels: tuple[float, ...]  # closes on T's basis
    events: tuple[Event, ...]

    def high(self, i: int) -> float:
        return self.bars[i].high * self.levels[i] / self.bars[i].close

    def low(self, i: int) -> float:
        return self.bars[i].low * self.levels[i] / self.bars[i].close

    def sma(self, sessions: int, offset: int = 0) -> float | None:
        end = len(self.levels) - offset
        if end - sessions < 0:
            return None
        return math.fsum(self.levels[end - sessions : end]) / sessions


def adjusted_window(bars: Sequence[DailyBar], sessions: Sequence[date]) -> Window:
    """Returns between consecutive bars across ex-dates (SC6) and closes on T's basis.
    `sessions`: the market sessions the bars lie in, so a return that spans one without a bar
    (no trade, or a lost session) is a raw ratio, marked `gap`."""
    position = {s: i for i, s in enumerate(sessions)}
    returns: list[float] = []
    events: list[Event] = []
    for before, bar in pairwise(bars):
        reference = before.close
        if bar.reference is not None:
            reference = bar.reference
            events.append(Event(bar.session, reference / before.close, "ex_reference"))
        elif bar.cash is not None or bar.stock_ratio is not None:
            reference = (before.close - (bar.cash or 0.0)) / (1 + (bar.stock_ratio or 0.0))
            events.append(Event(bar.session, reference / before.close, "dividend"))
        elif position[bar.session] - position[before.session] > 1:
            events.append(Event(bar.session, 1.0, "gap"))  # no bar in between: a raw ratio
        elif bar.change is not None and abs(bar.change) < EPSILON and bar.close != before.close:
            events.append(Event(bar.session, 1.0, "unexplained"))
        returns.append(bar.close / reference - 1)
    levels = [bars[-1].close]
    for r in reversed(returns):
        levels.append(levels[-1] / (1 + r))
    return Window(tuple(bars), tuple(returns), tuple(reversed(levels)), tuple(events))


# ---------- readings ----------


class SourceRow(BaseModel):
    bar_id: str
    feed: str
    feed_status: str
    published_at: datetime


class Metrics(BaseModel):
    close: Decimal
    change_1d: Decimal | None
    change_5d: Decimal | None
    z1: Decimal | None
    z5: Decimal | None
    volume_ratio: Decimal | None
    avg_trade_value: Decimal | None
    sma_20: Decimal | None
    sma_60: Decimal | None
    range_high: Decimal | None
    range_low: Decimal | None


@dataclass(frozen=True)
class StockReading:
    company: Company
    window: Window
    liquid: bool
    z1: float | None
    z5: float | None
    volume_ratio: float | None
    avg_trade_value: float | None
    flags: tuple[str, ...]

    @property
    def score(self) -> float | None:
        if self.z1 is None or self.z5 is None:
            return None
        return max(abs(self.z1), abs(self.z5))

    def range(self, sessions: int) -> tuple[float, float] | None:
        """(high, low) of the `sessions` sessions before T, on T's basis."""
        n = len(self.window.bars)
        if n < sessions + 1:
            return None
        span = range(n - 1 - sessions, n - 1)
        return max(self.window.high(i) for i in span), min(self.window.low(i) for i in span)

    def metrics(self, rules: "ScreenRuleSet") -> Metrics:
        w = self.window
        change = rules.movers.change_sessions
        r5 = w.levels[-1] / w.levels[-1 - change] - 1 if len(w.levels) > change else None
        found = self.range(20)
        return Metrics(
            close=Decimal(w.bars[-1].close_text),
            change_1d=_q(w.returns[-1] if w.returns else None),
            change_5d=_q(r5),
            z1=_q(self.z1),
            z5=_q(self.z5),
            volume_ratio=_q(self.volume_ratio),
            avg_trade_value=_q(self.avg_trade_value),
            sma_20=_q(w.sma(20)),
            sma_60=_q(w.sma(60)),
            range_high=_q(found[0]) if found else None,
            range_low=_q(found[1]) if found else None,
        )

    def source(self) -> SourceRow:
        bar = self.window.bars[-1]
        return SourceRow(
            bar_id=bar.row_id,
            feed=bar.feed,
            feed_status=bar.feed_status,
            published_at=bar.published_at,
        )


@dataclass(frozen=True)
class Unavailable:
    company: Company
    reason: Literal["no_trade", "history"]
    detail: str


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _stdev(values: Sequence[float]) -> float:
    mean = _mean(values)
    return math.sqrt(math.fsum((v - mean) ** 2 for v in values) / (len(values) - 1))


def read_stock(
    rules: ScreenRuleSet, company: Company, bars: Sequence[DailyBar], sessions: Sequence[date]
) -> StockReading | Unavailable:
    """One stock at T = sessions[-1], from its bars in the last `window_sessions` sessions.
    `bars`: the stock's bars known at T, oldest first, none after T (so the tail is read)."""
    window_sessions = sessions[-rules.window_sessions :]
    first = window_sessions[0]
    # a stored close of 0 is a session without trade: FinMind's placeholder rows, which its store
    # skips since M3.11 (the few stored before for the research universe are skipped here)
    own = [b for b in bars[-rules.window_sessions :] if b.session >= first and b.close > 0]
    if not own or own[-1].session != window_sessions[-1]:
        return Unavailable(company, "no_trade", f"no trade on {window_sessions[-1]}")
    if len(own) < rules.liquidity.min_history:
        return Unavailable(
            company,
            "history",
            f"{len(own)} sessions in the window, {rules.liquidity.min_history} needed",
        )
    w = adjusted_window(own, window_sessions)
    m = rules.movers
    values = [b.trade_value for b in own[-rules.liquidity.sessions :] if b.trade_value is not None]
    average = _mean(values) if len(values) * 2 >= rules.liquidity.sessions else None
    liquid = average is not None and average >= float(rules.liquidity.min_avg_trade_value_twd)
    z1 = z5 = None
    known = w.returns[-1 - m.volatility_sessions : -1]
    if len(known) == m.volatility_sessions:
        sigma = _stdev(known)
        if sigma > EPSILON:
            z1 = w.returns[-1] / sigma
            change = w.levels[-1] / w.levels[-1 - m.change_sessions] - 1
            z5 = change / (sigma * math.sqrt(m.change_sessions))
    prior = [b.volume for b in own[-1 - m.volume_sessions : -1]]
    volume_ratio = (
        own[-1].volume / _mean(prior)
        if len(prior) == m.volume_sessions and _mean(prior) > 0
        else None
    )
    flags: list[str] = []
    if any(e.source in ("ex_reference", "dividend") for e in w.events):
        flags.append("action_in_window")
    if any(e.source == "gap" for e in w.events):
        flags.append("gap_in_window")
    if any(e.source == "unexplained" for e in w.events):
        flags.append("unexplained_gap")
    recent = {b.session for b in own[-1 - m.volume_sessions :]}
    ratio = float(rules.action_flag_ratio)
    if any(e.session in recent and abs(e.factor - 1) > ratio for e in w.events):
        flags.append("volume_basis")
    return StockReading(company, w, liquid, z1, z5, volume_ratio, average, tuple(flags))


# ---------- movers and breadth ----------


class Mover(BaseModel):
    code: str
    name: str
    industry: str
    score: Decimal
    metrics: Metrics
    flags: list[str]
    source: SourceRow


def movers(rules: ScreenRuleSet, readings: Sequence[StockReading]) -> list[StockReading]:
    """The liquid stocks that moved most against their own history, largest change first."""
    m = rules.movers
    found = [
        r
        for r in readings
        if r.liquid
        and r.score is not None
        and (
            r.score >= float(m.z_threshold)
            or (r.volume_ratio is not None and r.volume_ratio >= float(m.volume_ratio))
        )
    ]
    return sorted(found, key=lambda r: (-(r.score or 0.0), r.company.code))


class Breadth(BaseModel):
    members: int
    above: int
    share: Decimal | None


def breadth(sessions: int, readings: Sequence[StockReading]) -> dict[str, Breadth]:
    """Per industry: its liquid stocks with a `sessions` average, and how many close above."""
    counts: dict[str, list[int]] = {}
    for r in readings:
        average = r.window.sma(sessions)
        if not r.liquid or average is None:
            continue
        found = counts.setdefault(r.company.industry, [0, 0])
        found[0] += 1
        found[1] += r.window.levels[-1] > average
    return {
        industry: Breadth(
            members=members, above=above, share=_q(above / members) if members else None
        )
        for industry, (members, above) in sorted(counts.items())
    }


# ---------- screens ----------


class ConditionReading(BaseModel):
    kind: str
    label: str
    status: Status
    value: Decimal | None = None
    threshold: Decimal | None = None


class NoteReading(BaseModel):
    kind: str
    label: str
    status: Status
    days: int | None = None
    of: int | None = None


def _condition(
    rules: ScreenRuleSet,
    condition: Condition,
    reading: StockReading,
    breadths: Mapping[str, Mapping[int, Breadth]],
) -> ConditionReading:
    w = reading.window
    label = condition.label(rules)

    def out(
        status: Status,
        value: float | Decimal | None = None,
        threshold: float | Decimal | None = None,
    ) -> ConditionReading:
        def q(x: float | Decimal | None) -> Decimal | None:
            return x.quantize(Q4) if isinstance(x, Decimal) else _q(x)

        return ConditionReading(
            kind=condition.kind, label=label, status=status, value=q(value), threshold=q(threshold)
        )

    if isinstance(condition, Liquid):
        return out(
            "pass" if reading.liquid else "fail",
            reading.avg_trade_value,
            rules.liquidity.min_avg_trade_value_twd,
        )
    if isinstance(condition, CloseAboveSma):
        average = w.sma(condition.sessions)
        if average is None:
            return out("unavailable")
        return out("pass" if w.levels[-1] > average else "fail", w.levels[-1], average)
    if isinstance(condition, SmaRising):
        now, then = w.sma(condition.sessions), w.sma(condition.sessions, condition.lookback)
        if now is None or then is None:
            return out("unavailable")
        return out("pass" if now > then else "fail", now, then)
    if isinstance(condition, RangeWidthMax):
        found = reading.range(condition.sessions)
        if found is None or found[1] <= 0:
            return out("unavailable")
        width = (found[0] - found[1]) / found[1] * 100
        return out(
            "pass" if width <= float(condition.percent) else "fail", width, condition.percent
        )
    if isinstance(condition, CloseAboveRangeHigh):
        found = reading.range(condition.sessions)
        if found is None:
            return out("unavailable")
        return out("pass" if w.levels[-1] > found[0] else "fail", w.levels[-1], found[0])
    if isinstance(condition, VolumeMultipleMin):
        prior = [b.volume for b in w.bars[-1 - condition.sessions : -1]]
        if len(prior) < condition.sessions or _mean(prior) <= 0:
            return out("unavailable")
        multiple = w.bars[-1].volume / _mean(prior)
        return out(
            "pass" if multiple >= float(condition.multiple) else "fail",
            multiple,
            condition.multiple,
        )
    found_breadth = breadths.get(reading.company.industry, {}).get(condition.sessions)
    if found_breadth is None or found_breadth.members < condition.min_members:
        return out("not_applicable", found_breadth.members if found_breadth else 0)
    share = found_breadth.share or Decimal(0)
    return out("pass" if share >= condition.share else "fail", share, condition.share)


def _note(note: FlowNetBuy, flows: Sequence[Flow], sessions: Sequence[date]) -> NoteReading:
    wanted = set(sessions[-note.sessions :])
    found = [f for f in flows if f.session in wanted]
    if len(found) < note.sessions:
        return NoteReading(kind=note.kind, label=note.label(), status="unavailable")
    days = sum((f.foreign if note.investor == "foreign" else f.trust) > 0 for f in found)
    return NoteReading(
        kind=note.kind,
        label=note.label(),
        status="pass" if days >= note.min_days else "fail",
        days=days,
        of=note.sessions,
    )


def verdict(conditions: Sequence[ConditionReading]) -> Literal["meets", "fails", "unavailable"]:
    statuses = {c.status for c in conditions}
    if "fail" in statuses:
        return "fails"
    if "unavailable" in statuses:
        return "unavailable"
    return "meets"


def _invalidated(screen: Screen, reading: StockReading, level: Decimal | None) -> str | None:
    w = reading.window
    for rule in screen.invalidation:
        if isinstance(rule, ClosesBelowSma):
            below = 0
            for offset in range(rule.consecutive):
                average = w.sma(rule.sessions, offset)
                if average is None or w.levels[-1 - offset] >= average:
                    break
                below += 1
            if below == rule.consecutive:
                return rule.label()
        elif level is not None and w.levels[-1] < float(level):
            return rule.label()
    return None


class WatchLine(BaseModel):
    code: str
    name: str
    industry: str
    state: State
    entered: date
    sessions: int
    level: Decimal | None
    still_meets: bool | None  # None: no reading at T
    reason: str | None
    conditions: list[ConditionReading]
    notes: list[NoteReading]
    metrics: Metrics | None
    flags: list[str]
    source: SourceRow | None
    score: Decimal | None


class WatchedOut(BaseModel):
    code: str
    entered: date
    sessions: int
    level: Decimal | None


class ScreenResult(BaseModel):
    screen_id: str
    name_zh: str
    meeting: int
    unavailable: int
    lines: list[WatchLine]  # entered, on watch, invalidated and expired, by change
    watch: list[WatchedOut]  # the list carried to the next run


def _factor_since(window: Window, after: date) -> float:
    """The product of the action factors after `after` up to T (a level moves with them)."""
    product = 1.0
    for event in window.events:
        if event.session > after and event.source in ("ex_reference", "dividend"):
            product *= event.factor
    return product


def judge_screen(
    rules: ScreenRuleSet,
    screen: Screen,
    session: date,
    readings: Mapping[str, StockReading],
    companies: Mapping[str, Company],
    breadths: Mapping[str, Mapping[int, Breadth]],
    flows: Mapping[str, Sequence[Flow]],
    sessions: Sequence[date],
    previous: PreviousRun | None,
) -> ScreenResult:
    """One screen at T: who meets it, and the watch list advanced (SC9)."""
    judged: dict[str, tuple[list[ConditionReading], bool]] = {}
    unavailable = 0
    for code, stock in readings.items():
        conditions = [_condition(rules, c, stock, breadths) for c in screen.conditions]
        result = verdict(conditions)
        unavailable += result == "unavailable"
        judged[code] = (conditions, result == "meets")

    def line(
        code: str,
        state: State,
        entered: date,
        count: int,
        level: Decimal | None,
        reason: str | None = None,
    ) -> WatchLine:
        reading = readings.get(code)
        company = companies[code]
        conditions, meets = judged.get(code, ([], False))
        return WatchLine(
            code=code,
            name=company.name,
            industry=company.industry,
            state=state,
            entered=entered,
            sessions=count,
            level=level,
            still_meets=meets if reading is not None else None,
            reason=reason,
            conditions=conditions,
            notes=[_note(n, flows.get(code, ()), sessions) for n in screen.notes],
            metrics=reading.metrics(rules) if reading else None,
            flags=list(reading.flags) if reading else ["no_reading"],
            source=reading.source() if reading else None,
            score=_q(reading.score) if reading else None,
        )

    lines: list[WatchLine] = []
    carried: dict[str, Watched] = {}
    level_sessions = screen.level_sessions()
    for watched in previous.watch.get(screen.screen_id, ()) if previous else ():
        reading = readings.get(watched.code)
        if watched.code not in companies:
            continue  # no longer listed
        count = watched.sessions + 1
        level = watched.level
        if reading is not None and level is not None and previous is not None:
            level = Decimal(float(level) * _factor_since(reading.window, previous.session))
            level = level.quantize(Q4)
        reason = _invalidated(screen, reading, level) if reading is not None else None
        meets = judged.get(watched.code, ([], False))[1]
        if reason is not None:
            lines.append(line(watched.code, "invalidated", watched.entered, count, level, reason))
        elif count > rules.watch_sessions and not meets:
            lines.append(line(watched.code, "expired", watched.entered, count, level))
        else:
            carried[watched.code] = Watched(watched.code, watched.entered, count, level)
            lines.append(line(watched.code, "on_watch", watched.entered, count, level))
    for code, (_, meets) in judged.items():
        if not meets or code in carried or any(x.code == code for x in lines):
            continue
        level = None
        if level_sessions is not None:
            found = readings[code].range(level_sessions)
            level = _q(found[0]) if found else None
        carried[code] = Watched(code, session, 1, level)
        lines.append(line(code, "entered", session, 1, level))
    order = {"entered": 0, "on_watch": 1, "invalidated": 2, "expired": 3}
    lines.sort(key=lambda x: (order[x.state], -(x.score or Decimal(0)), x.code))
    return ScreenResult(
        screen_id=screen.screen_id,
        name_zh=screen.name_zh,
        meeting=sum(meets for _, meets in judged.values()),
        unavailable=unavailable,
        lines=lines,
        watch=[
            WatchedOut(code=w.code, entered=w.entered, sessions=w.sessions, level=w.level)
            for w in sorted(carried.values(), key=lambda w: w.code)
        ],
    )


# ---------- a run ----------


class Coverage(BaseModel):
    listed: int
    expected: int  # listed companies with a bar in the sessions just before T
    covered: int  # of which with a bar at T
    ratio: Decimal | None
    read: int
    unavailable: dict[str, int]
    liquid: int


class ScreenRunOut(BaseModel):
    market: Literal["TW"]
    session: date
    known_at: datetime
    rule_version: str
    status: Literal["judged", "not_judged"]
    reason: str | None
    coverage: Coverage
    industry_basis: str
    breadth: dict[str, Breadth]
    movers: list[Mover]
    movers_count: int
    screens: list[ScreenResult]

    def counts(self) -> dict[str, object]:
        """The run's counts (screen_runs.counts): enough for the history check."""
        return {
            "listed": self.coverage.listed,
            "covered": self.coverage.covered,
            "liquid": self.coverage.liquid,
            "movers": self.movers_count,
            "screens": {
                s.screen_id: {
                    "meeting": s.meeting,
                    **{
                        state: sum(x.state == state for x in s.lines)
                        for state in ("entered", "on_watch", "invalidated", "expired")
                    },
                }
                for s in self.screens
            },
        }


def coverage_of(
    rules: ScreenRuleSet,
    bars: Mapping[str, Sequence[DailyBar]],
    sessions: Sequence[date],
) -> tuple[int, int]:
    """(expected, covered): the listed companies with a bar in the `lookback_sessions` before T,
    and how many of them have one at T."""
    before = set(sessions[-1 - rules.readiness.lookback_sessions : -1])
    session = sessions[-1]
    expected = covered = 0
    for own in bars.values():
        recent = {b.session for b in own[-1 - rules.readiness.lookback_sessions :]}
        if recent & before:
            expected += 1
            covered += session in recent
    return expected, covered


def _not_ready(rules: ScreenRuleSet, session: date, coverage: Coverage) -> str | None:
    """Why the session is not judged (SC10), or None when it is ready."""
    readiness = rules.readiness
    ratio = Decimal(coverage.covered) / Decimal(coverage.expected) if coverage.expected else None
    if ratio is None or ratio < readiness.min_coverage:
        return (
            f"bars of {session} for {coverage.covered} of {coverage.expected} listed companies "
            f"({(ratio or Decimal(0)) * 100:.1f}%), below "
            f"{readiness.min_coverage * 100:.0f}%: not judged"
        )
    traded = coverage.read + coverage.unavailable.get("history", 0)
    share = Decimal(coverage.read) / Decimal(traded) if traded else None
    if readiness.min_history_share is not None and (
        share is None or share < readiness.min_history_share
    ):
        return (
            f"{coverage.read} of the {traded} companies with a bar of {session} have "
            f"{rules.liquidity.min_history} sessions of history "
            f"({(share or Decimal(0)) * 100:.1f}%), below "
            f"{readiness.min_history_share * 100:.0f}%: not judged"
        )
    return None


def evaluate(
    rules: ScreenRuleSet,
    *,
    known_at: datetime,
    companies: Mapping[str, Company],
    bars: Mapping[str, Sequence[DailyBar]],
    sessions: Sequence[date],
    flows: Mapping[str, Sequence[Flow]],
    previous: PreviousRun | None,
    industry_basis: str,
) -> ScreenRunOut:
    """The screens at T = sessions[-1] over `companies` (the listed set, receipts left out),
    with each one's bars (oldest first) known at T; not judged below the coverage or, since
    0.2.0, the share of them with enough history (SC10)."""
    session = sessions[-1]
    expected, covered = coverage_of(rules, bars, sessions)
    ratio = Decimal(covered) / Decimal(expected) if expected else None
    readings: dict[str, StockReading] = {}
    unavailable = {"no_trade": 0, "history": 0}
    for code in sorted(companies):
        found = read_stock(rules, companies[code], bars.get(code, ()), sessions)
        if isinstance(found, Unavailable):
            unavailable[found.reason] += 1
        else:
            readings[code] = found
    coverage = Coverage(
        listed=len(companies),
        expected=expected,
        covered=covered,
        ratio=ratio.quantize(Q4) if ratio is not None else None,
        read=len(readings),
        unavailable=unavailable,
        liquid=sum(r.liquid for r in readings.values()),
    )
    reason = _not_ready(rules, session, coverage)
    if reason is not None:
        return ScreenRunOut(
            market=rules.market,
            session=session,
            known_at=known_at,
            rule_version=rules.rule_version,
            status="not_judged",
            reason=reason,
            coverage=coverage,
            industry_basis=industry_basis,
            breadth={},
            movers=[],
            movers_count=0,
            screens=[],
        )
    breadth_sessions = sorted(
        {
            c.sessions
            for s in rules.screens
            for c in s.conditions
            if isinstance(c, IndustryBreadthMin)
        }
    )
    per_sessions = {n: breadth(n, list(readings.values())) for n in breadth_sessions}
    breadths: dict[str, dict[int, Breadth]] = {}
    for n, found_breadth in per_sessions.items():
        for industry, value in found_breadth.items():
            breadths.setdefault(industry, {})[n] = value
    moved = movers(rules, list(readings.values()))
    return ScreenRunOut(
        market=rules.market,
        session=session,
        known_at=known_at,
        rule_version=rules.rule_version,
        status="judged",
        reason=None,
        coverage=coverage,
        industry_basis=industry_basis,
        breadth=per_sessions.get(breadth_sessions[0], {}) if breadth_sessions else {},
        movers=[
            Mover(
                code=r.company.code,
                name=r.company.name,
                industry=r.company.industry,
                score=_q(r.score) or Decimal(0),
                metrics=r.metrics(rules),
                flags=list(r.flags),
                source=r.source(),
            )
            for r in moved[: rules.movers.page_top]
        ],
        movers_count=len(moved),
        screens=[
            judge_screen(
                rules, screen, session, readings, companies, breadths, flows, sessions, previous
            )
            for screen in rules.screens
        ],
    )


def previous_of(run: ScreenRunOut) -> PreviousRun:
    """The watch lists a judged run carries to the next one."""
    return PreviousRun(
        session=run.session,
        watch={
            s.screen_id: [Watched(w.code, w.entered, w.sessions, w.level) for w in s.watch]
            for s in run.screens
        },
    )


# ---------- the history check ----------


class HistorySummary(BaseModel):
    screen_id: str
    sessions: int
    median_meeting: Decimal | None
    zero_share: Decimal | None
    max_meeting: int | None


def history_summary(
    screen_ids: Sequence[str], counts: Sequence[Mapping[str, object]]
) -> list[HistorySummary]:
    """Per screen, over judged runs' counts: how many met it per session (median, max) and the
    share of sessions none did. Never returns after the hits (OD-7)."""
    out = []
    for screen_id in screen_ids:
        meeting: list[int] = []
        for c in counts:
            screens = c.get("screens")
            if isinstance(screens, Mapping) and isinstance(screens.get(screen_id), Mapping):
                meeting.append(int(screens[screen_id]["meeting"]))
        if not meeting:
            out.append(
                HistorySummary(
                    screen_id=screen_id,
                    sessions=0,
                    median_meeting=None,
                    zero_share=None,
                    max_meeting=None,
                )
            )
            continue
        ordered = sorted(meeting)
        mid = len(ordered) // 2
        median = (
            Decimal(ordered[mid])
            if len(ordered) % 2
            else (Decimal(ordered[mid - 1]) + Decimal(ordered[mid])) / 2
        )
        out.append(
            HistorySummary(
                screen_id=screen_id,
                sessions=len(meeting),
                median_meeting=median,
                zero_share=(Decimal(sum(m == 0 for m in meeting)) / len(meeting)).quantize(Q4),
                max_meeting=max(meeting),
            )
        )
    return out
