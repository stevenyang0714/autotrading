"""Signal convergence (M1.7, ADR-028; build spec 02 §16, research report 01 §15). Pure; no I/O.

A company's level at a time T, from what was known then:
- items: the readings of its buyback state assignment at T (the buyback state, valuation support,
  market confirmation) and the Phase 1 events of the last `window_days` (earnings releases,
  10-K/10-Q filings, buyback announcements, buyback state changes), deduplicated by source so
  that one filing counts once however many rows it produced;
- L0 Information: at least one item;
- L1 Watch: at least `min_items` items, `min_signals` of them readings;
- L2 Thesis: the S1 causal chain from two independent families: buybacks executed (state ACTIVE
  or HIGH-CONVICTION, family 2) and valuation support (DCF discount or FCF yield above its own
  median, family 3);
- L3 Trade Candidate: L2, market confirmation (family 5) and the S1 strategy trigger (the
  ACTIVE or HIGH-CONVICTION signal);
- L4 Execution Ready: needs a risk check, liquidity, sizing and compliance; unreachable in
  Phase 1 (P1-4).
The level is the highest one passing with every level below it. No level places an order.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EventKind = Literal[
    "earnings_release", "periodic_report", "buyback_statement", "buyback_state_change"
]
Status = Literal["pass", "fail", "unavailable"]
LEVEL_NAMES = ("Information", "Watch", "Thesis", "Trade Candidate", "Execution Ready")
EVENT_FAMILY: dict[EventKind, int] = {
    "earnings_release": 4,
    "periodic_report": 3,
    "buyback_statement": 2,
    "buyback_state_change": 2,
}
SIGNAL_STATES = ("watch", "active", "high_conviction")
L4_DETAIL = "needs the Phase 2 risk check, liquidity, sizing and compliance (P1-4)"


# ---------- rules ----------


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatchRule(_Rule):
    window_days: Annotated[int, Field(gt=0)]
    min_items: Annotated[int, Field(gt=0)]
    min_signals: Annotated[int, Field(ge=0)]


class ThesisRule(_Rule):
    buyback_states: list[str]
    valuation_conditions: list[str]


class TradeCandidateRule(_Rule):
    market_conditions: list[str]


class LevelRules(_Rule):
    watch: WatchRule
    thesis: ThesisRule
    trade_candidate: TradeCandidateRule


class AlertRuleSet(_Rule):
    """One released rule version: immutable, like the buyback rule sets (ADR-025 B4)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    buyback_rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    event_kinds: list[EventKind]
    buyback_statement_kinds: list[str]
    event_lookback_days: Annotated[int, Field(gt=0)]
    levels: LevelRules

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"})

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class AlertRuleSetEntry(AlertRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> AlertRuleSet:
        return AlertRuleSet.model_validate(self.content())


class AlertRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[AlertRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "AlertRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> AlertRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


# ---------- inputs ----------


@dataclass(frozen=True)
class Event:
    """A Phase 1 event of one company, public at `known_at`."""

    kind: EventKind
    table: str
    row_id: str
    source: str  # what makes events independent: the accession number, or the row
    known_at: datetime
    label: str

    @property
    def key(self) -> str:
        return f"event:{self.table}:{self.row_id}"


@dataclass(frozen=True)
class Condition:
    status: Status
    value: str | None


@dataclass(frozen=True)
class BuybackReading:
    """A stored buyback state assignment: its state and condition readings at its T."""

    assignment_id: str
    state: str
    known_at: datetime
    rule_version: str
    conditions: dict[str, Condition]


# ---------- result ----------


class Item(BaseModel):
    kind: Literal["reading", "event"]
    family_id: int
    label: str
    table: str
    row_id: str
    source: str
    known_at: datetime
    detail: str | None = None


class LevelCheck(BaseModel):
    level: int
    name: str
    status: Status
    detail: str


class Convergence(BaseModel):
    """Everything a convergence assessment stores: recomputing it gives the same document."""

    rule_version: str
    buyback_rule_version: str
    known_at: datetime
    level: int | None  # None: nothing in the window
    levels: list[LevelCheck]
    items: list[Item]
    independent_families: list[int]


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _status_text(status: Status) -> str:
    return {"pass": "passes", "fail": "fails", "unavailable": "unavailable"}[status]


def level_name(level: int | None) -> str:
    return "none" if level is None else f"L{level} {LEVEL_NAMES[level]}"


def _any(conditions: dict[str, Condition], ids: Sequence[str]) -> Status:
    """pass if any listed condition passes; unavailable when none could be evaluated."""
    statuses = [conditions[i].status for i in ids if i in conditions]
    if "pass" in statuses:
        return "pass"
    if not statuses or all(s == "unavailable" for s in statuses):
        return "unavailable"
    return "fail"


def _readings(rules: AlertRuleSet, buyback: BuybackReading | None) -> list[Item]:
    """The assignment's readings that pass: the buyback signal (WATCH or above), valuation
    support and market confirmation, each its own source."""
    if buyback is None:
        return []

    def reading(family_id: int, label: str, source: str, detail: str) -> Item:
        return Item(
            kind="reading",
            family_id=family_id,
            label=label,
            table="buyback_state_assignments",
            row_id=buyback.assignment_id,
            source=f"{source}:{buyback.assignment_id}",
            known_at=buyback.known_at,
            detail=detail,
        )

    found = []
    if buyback.state in SIGNAL_STATES:
        state = buyback.state.replace("_", "-").upper()
        found.append(
            reading(
                2,
                f"Buyback state {state}",
                "buyback_state_assignments",
                f"rules {buyback.rule_version}",
            )
        )
    valuation = rules.levels.thesis.valuation_conditions
    if _any(buyback.conditions, valuation) == "pass":
        passed = ", ".join(c for c in valuation if _passed(buyback, c))
        found.append(reading(3, "Valuation support", "valuation", passed))
    market = rules.levels.trade_candidate.market_conditions
    if _any(buyback.conditions, market) == "pass":
        passed = ", ".join(c for c in market if _passed(buyback, c))
        found.append(reading(5, "Market confirmation", "market", passed))
    return found


def _passed(buyback: BuybackReading, condition_id: str) -> bool:
    condition = buyback.conditions.get(condition_id)
    return condition is not None and condition.status == "pass"


def in_window(events: Sequence[Event], at: datetime, days: int) -> list[Event]:
    """Events public in the `days` up to T, one per source (the earliest row of each)."""
    start = at - timedelta(days=days)
    seen: dict[str, Event] = {}
    for event in sorted(events, key=lambda e: (e.known_at, e.key)):
        if start < event.known_at <= at and event.source not in seen:
            seen[event.source] = event
    return list(seen.values())


def assess(
    rules: AlertRuleSet,
    at: datetime,
    buyback: BuybackReading | None,
    events: Sequence[Event],
) -> Convergence:
    """The level of one company at T (ADR-028 A2)."""
    readings = _readings(rules, buyback)
    windowed = [
        Item(
            kind="event",
            family_id=EVENT_FAMILY[e.kind],
            label=e.label,
            table=e.table,
            row_id=e.row_id,
            source=e.source,
            known_at=e.known_at,
        )
        for e in in_window(
            [e for e in events if e.kind in rules.event_kinds], at, rules.levels.watch.window_days
        )
    ]
    read = {i.source for i in readings}
    items = readings + [i for i in windowed if i.source not in read]
    watch = rules.levels.watch
    l0: Status = "pass" if items else "fail"
    l1: Status = (
        "pass" if len(items) >= watch.min_items and len(readings) >= watch.min_signals else "fail"
    )
    thesis = rules.levels.thesis
    if buyback is None:
        l2: Status = "unavailable"
        l2_detail = "no buyback state assignment at this date"
    else:
        executed = buyback.state in thesis.buyback_states
        valuation = _any(buyback.conditions, thesis.valuation_conditions)
        l2 = "pass" if executed and valuation == "pass" else "fail"
        if not executed:
            l2_detail = f"buyback state {buyback.state.replace('_', '-').upper()}: not executing"
        elif valuation != "pass":
            l2_detail = (
                "no valuation reading" if valuation == "unavailable" else "no valuation support"
            )
            if valuation == "unavailable":
                l2 = "unavailable"
        else:
            l2_detail = "buybacks executed and valuation support"
    market = (
        _any(buyback.conditions, rules.levels.trade_candidate.market_conditions)
        if buyback
        else "unavailable"
    )
    l3: Status = "pass" if l2 == "pass" and market == "pass" else "fail"
    if l2 == "pass" and market == "unavailable":
        l3 = "unavailable"
    levels = [
        LevelCheck(level=0, name=LEVEL_NAMES[0], status=l0, detail=_count(len(items), "item")),
        LevelCheck(
            level=1,
            name=LEVEL_NAMES[1],
            status=l1,
            detail=f"{_count(len(items), 'item')}, {_count(len(readings), 'reading')} "
            f"(needs {watch.min_items} and {watch.min_signals})",
        ),
        LevelCheck(level=2, name=LEVEL_NAMES[2], status=l2, detail=l2_detail),
        LevelCheck(
            level=3,
            name=LEVEL_NAMES[3],
            status=l3,
            detail=(
                f"market confirmation {_status_text(market)}"
                if l2 == "pass"
                else f"needs L2 first (market confirmation {_status_text(market)})"
            ),
        ),
        LevelCheck(level=4, name=LEVEL_NAMES[4], status="unavailable", detail=L4_DETAIL),
    ]
    level: int | None = None
    for check in levels:
        if check.status != "pass":
            break
        level = check.level
    return Convergence(
        rule_version=rules.rule_version,
        buyback_rule_version=rules.buyback_rule_version,
        known_at=at,
        level=level,
        levels=levels,
        items=items,
        independent_families=sorted({i.family_id for i in items}),
    )


# ---------- alerts ----------


@dataclass(frozen=True)
class AlertIn:
    kind: Literal["event", "level_change"]
    level: int
    previous_level: int | None
    direction: Literal["up", "down"] | None
    title: str
    source_key: str
    known_at: datetime
    evidence: list[dict[str, str]]


def level_alert(
    ticker: str, current: Convergence, previous: int | None, source_key: str
) -> AlertIn | None:
    """An alert when the level changes and either side is L1 or above (moves between none and
    L0 are covered by the event alerts)."""
    now = current.level
    if now == previous or max(now if now is not None else -1, previous or -1) < 1:
        return None
    up = (now if now is not None else -1) > (previous if previous is not None else -1)
    if up:
        title = f"{ticker} reached {level_name(now)}"
    else:
        title = f"{ticker} fell to {level_name(now)} from {level_name(previous)}"
    return AlertIn(
        kind="level_change",
        level=now if now is not None else 0,
        previous_level=previous,
        direction="up" if up else "down",
        title=title,
        source_key=source_key,
        known_at=current.known_at,
        evidence=[{"table": i.table, "id": i.row_id, "label": i.label} for i in current.items],
    )


def event_alert(ticker: str, event: Event) -> AlertIn:
    return AlertIn(
        kind="event",
        level=0,
        previous_level=None,
        direction=None,
        title=f"{ticker}: {event.label}",
        source_key=event.key,
        known_at=event.known_at,
        evidence=[{"table": event.table, "id": event.row_id, "label": event.label}],
    )


def new_events(
    events: Sequence[Event], since: datetime | None, at: datetime, lookback_days: int
) -> list[Event]:
    """Events public after the previous assessment (at most `lookback_days` back) up to T."""
    floor = at - timedelta(days=lookback_days)
    start = max(since, floor) if since is not None else floor
    return sorted((e for e in events if start < e.known_at <= at), key=lambda e: e.known_at)
