"""The Taiwan screens' runs (M3.11, ADR-042): their inputs as known at T and held at S, each run
stored once (append-only), the backfill and its verify, and the candidates whose institutional
flows FinMind fetches.

- Inputs: the listed companies (receipts left out, each counted from its listing date), their
  raw bars, price change, trade value, ex-date reference price, announced dividends and flows.
  A value counts at T when published by T and recorded by S; a later revision (TW18) counts
  from its publication on.
- A scheduled run judges the newest session stored that is not judged yet; when every stored
  session is judged and the TWSE calendar names a later one, that session is recorded as not
  judged (its files have not come). A backfill judges every session in order, in batches of
  BATCH_SESSIONS with the window before each, the watch lists carried from run to run, and the
  industry as first known (the company file was first fetched with M3.11; SC13).
- The candidates are the latest judged run's new and watched names, then its movers, the
  universe left out (its flows come every day), at most the requests the rules allow.
Nothing here reads the holdings ledger (ADR-041 H4).
"""

import bisect
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic_core import to_jsonable_python
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from autotrading.db.models import (
    DividendEvent,
    ExchangeMeasure,
    PriceBar,
    ScreenRun,
    SplitEvent,
)
from autotrading.db.models import ScreenRuleSet as ScreenRuleSetRow
from autotrading.domain.market_calendar import MarketCalendar
from autotrading.domain.markets import TW
from autotrading.domain.provenance import end_of_day
from autotrading.domain.screens import (
    Company,
    DailyBar,
    Flow,
    PreviousRun,
    ScreenRuleSet,
    ScreenRulesFile,
    ScreenRunOut,
    Watched,
    evaluate,
    previous_of,
)
from autotrading.repositories.listed import Listed, listed_at
from autotrading.settings import get_settings

ZONE = "Asia/Taipei"
BATCH_SESSIONS = 20  # sessions judged per loaded batch of the backfill
MEASURES = (
    "price_change",
    "trade_value",
    "ex_reference_price",
    "inst_foreign_net",
    "inst_trust_net",
)
UNIVERSE_FLOW_REQUESTS = 2  # the daily flows run: two datasets per universe code


@lru_cache
def _file(path: Path) -> ScreenRulesFile:
    return ScreenRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def active_screen_version() -> str:
    return _file(get_settings().resolved_config_dir() / "screen_rules.yaml").active().rule_version


def stored_screen_rules(session: Session, rule_version: str | None = None) -> ScreenRuleSet | None:
    """A released screen rule set as `make migrate` registered it; None when not loaded."""
    version = rule_version or active_screen_version()
    row = session.scalars(
        select(ScreenRuleSetRow).where(ScreenRuleSetRow.rule_version == version)
    ).first()
    return ScreenRuleSet.model_validate(row.content) if row else None


# ---------- inputs ----------


def _visible(model: Any, system_time: datetime | None) -> ColumnElement[bool]:
    if system_time is None:
        return model.superseded_at.is_(None)  # type: ignore[no-any-return]
    return and_(
        model.recorded_at <= system_time,
        or_(model.superseded_at.is_(None), model.superseded_at > system_time),
    )


@dataclass
class Universe:
    """The listed companies a run reads, with their instruments and listing dates."""

    companies: dict[str, Company]
    ids: dict[str, UUID]
    listed_on: dict[str, date | None]
    basis: str

    def at(self, session_date: date) -> dict[str, Company]:
        """The companies listed by `session_date` (a company counts from its listing date)."""
        return {
            code: c
            for code, c in self.companies.items()
            if (self.listed_on[code] or session_date) <= session_date
        }


def universe_of(
    session: Session,
    rules: ScreenRuleSet,
    *,
    known_at: datetime,
    system_time: datetime | None,
    first_known: bool,
) -> Universe:
    """The listed companies as known at T (or, for a backfill, as first known: SC13), receipts
    and the rules' other excluded industries left out."""
    listed: dict[str, Listed] = listed_at(session, None if first_known else known_at, system_time)
    kept = {code: c for code, c in listed.items() if c.industry not in rules.exclude_industries}
    basis = "as_known"
    if first_known and listed:
        first = min(c.published_at for c in listed.values()).astimezone(TW.zone).date()
        basis = f"first_known {first}"
    return Universe(
        companies={code: Company(code, c.short_name, c.industry) for code, c in kept.items()},
        ids={code: c.instrument_id for code, c in kept.items()},
        listed_on={code: c.listed_on for code, c in kept.items()},
        basis=basis,
    )


def market_sessions(
    session: Session,
    ids: Iterable[UUID],
    *,
    until: date,
    known_at: datetime,
    system_time: datetime | None,
    since: date | None = None,
) -> list[date]:
    """The sessions any of these companies has a bar for, known at T and held at S."""
    query = (
        select(PriceBar.bar_date)
        .distinct()
        .where(
            PriceBar.instrument_id.in_(list(ids)),
            PriceBar.adjustment == "raw",
            PriceBar.bar_date <= until,
            PriceBar.published_at <= known_at,
            _visible(PriceBar, system_time),
        )
    )
    if since is not None:
        query = query.where(PriceBar.bar_date >= since)
    return sorted(session.scalars(query))


@dataclass
class _Versions:
    """The visible versions of one company's values, by session, oldest publication first."""

    bars: dict[date, list[tuple[datetime, Any]]] = field(default_factory=dict)
    measures: dict[tuple[date, str], list[tuple[datetime, float]]] = field(default_factory=dict)
    cash: dict[date, float] = field(default_factory=dict)
    stock: dict[date, float] = field(default_factory=dict)


def _latest[V](versions: list[tuple[datetime, V]], known_at: datetime) -> V | None:
    found = None
    for published, value in versions:
        if published <= known_at:
            found = value
    return found


@dataclass
class Loaded:
    """A range of sessions' inputs, resolved at each T's known_at. A value with one version is
    built once and reused while its publication is before T (the common case, so a backfill
    stays fast); a session with a revision is resolved at every T."""

    sessions: list[date]
    versions: dict[str, _Versions]
    flow_codes: set[str]
    _cache: dict[tuple[str, date], tuple[datetime, DailyBar | None]] = field(default_factory=dict)

    def _resolve(self, code: str, day: date, known_at: datetime) -> DailyBar | None:
        found = self.versions[code]
        key = (code, day)
        cached = self._cache.get(key)
        if cached is not None and cached[0] <= known_at:
            return cached[1]
        bars = found.bars.get(day)
        if not bars:
            return None
        lists = [bars] + [
            found.measures[(day, m)]
            for m in ("trade_value", "price_change", "ex_reference_price")
            if (day, m) in found.measures
        ]
        single = all(len(v) == 1 for v in lists)
        row = _latest(bars, known_at)
        if row is None:
            return None

        def measure(measure_id: str) -> float | None:
            values = found.measures.get((day, measure_id))
            return _latest(values, known_at) if values else None

        bar = DailyBar(
            session=day,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            close_text=str(row.close),
            volume=float(row.volume),
            trade_value=measure("trade_value"),
            change=measure("price_change"),
            reference=measure("ex_reference_price"),
            cash=found.cash.get(day),
            stock_ratio=found.stock.get(day),
            feed=row.feed,
            feed_status=row.feed_status,
            row_id=str(row.id),
            published_at=row.published_at,
        )
        published = max(v[-1][0] for v in lists)
        if single and published <= known_at:  # every value counts already: reuse from here on
            self._cache[key] = (published, bar)
        return bar

    def bars_at(self, code: str, upto: Sequence[date], known_at: datetime) -> list[DailyBar]:
        if code not in self.versions:
            return []
        out = []
        for day in upto:
            bar = self._resolve(code, day, known_at)
            if bar is not None:
                out.append(bar)
        return out

    def flows_at(self, code: str, upto: Sequence[date], known_at: datetime) -> list[Flow]:
        if code not in self.flow_codes:
            return []
        found = self.versions[code]
        out = []
        for day in upto:
            foreign = found.measures.get((day, "inst_foreign_net"))
            trust = found.measures.get((day, "inst_trust_net"))
            f = _latest(foreign, known_at) if foreign else None
            t = _latest(trust, known_at) if trust else None
            if f is not None and t is not None:
                out.append(Flow(day, f, t))
        return out


def load(
    session: Session,
    universe: Universe,
    *,
    since: date,
    until: date,
    known_at: datetime,
    system_time: datetime | None,
) -> Loaded:
    """Every visible version of the companies' values over [since, until] published by
    `known_at` (the last T's)."""
    code_of = {v: k for k, v in universe.ids.items()}
    ids = list(code_of)
    versions: dict[str, _Versions] = defaultdict(_Versions)
    bars = session.execute(
        select(
            PriceBar.instrument_id,
            PriceBar.bar_date,
            PriceBar.published_at,
            PriceBar.id,
            PriceBar.open,
            PriceBar.high,
            PriceBar.low,
            PriceBar.close,
            PriceBar.volume,
            PriceBar.feed,
            PriceBar.feed_status,
        )
        .where(
            PriceBar.instrument_id.in_(ids),
            PriceBar.adjustment == "raw",
            PriceBar.bar_date.between(since, until),
            PriceBar.published_at <= known_at,
            _visible(PriceBar, system_time),
        )
        .order_by(PriceBar.published_at, PriceBar.recorded_at)
    )
    days: set[date] = set()
    for row in bars:
        versions[code_of[row.instrument_id]].bars.setdefault(row.bar_date, []).append(
            (row.published_at, row)
        )
        days.add(row.bar_date)
    measures = session.execute(
        select(
            ExchangeMeasure.instrument_id,
            ExchangeMeasure.session_date,
            ExchangeMeasure.measure_id,
            ExchangeMeasure.value,
            ExchangeMeasure.published_at,
        )
        .where(
            ExchangeMeasure.instrument_id.in_(ids),
            ExchangeMeasure.measure_id.in_(MEASURES),
            ExchangeMeasure.session_date.between(since, until),
            ExchangeMeasure.published_at <= known_at,
            _visible(ExchangeMeasure, system_time),
        )
        .order_by(ExchangeMeasure.published_at, ExchangeMeasure.recorded_at)
    )
    flow_codes: set[str] = set()
    for m in measures:
        code = code_of[m.instrument_id]
        versions[code].measures.setdefault((m.session_date, m.measure_id), []).append(
            (m.published_at, float(m.value))
        )
        if m.measure_id == "inst_foreign_net":
            flow_codes.add(code)
    recorded = (lambda c: c <= system_time) if system_time is not None else (lambda c: True)
    for d in session.execute(
        select(
            DividendEvent.instrument_id,
            DividendEvent.ex_date,
            DividendEvent.rate,
            DividendEvent.recorded_at,
        ).where(
            DividendEvent.instrument_id.in_(ids),
            DividendEvent.ex_date.between(since, until),
            DividendEvent.special.is_(False),
            DividendEvent.published_at <= known_at,
        )
    ):
        if recorded(d.recorded_at):
            cash = versions[code_of[d.instrument_id]].cash
            cash[d.ex_date] = cash.get(d.ex_date, 0.0) + float(d.rate)
    for s in session.execute(
        select(
            SplitEvent.instrument_id,
            SplitEvent.ex_date,
            SplitEvent.new_rate,
            SplitEvent.old_rate,
            SplitEvent.recorded_at,
        ).where(
            SplitEvent.instrument_id.in_(ids),
            SplitEvent.ex_date.between(since, until),
            SplitEvent.published_at <= known_at,
        )
    ):
        if recorded(s.recorded_at):
            versions[code_of[s.instrument_id]].stock[s.ex_date] = float(s.new_rate / s.old_rate - 1)
    return Loaded(sorted(days), dict(versions), flow_codes)


def _inputs_at(
    loaded: Loaded, universe: Universe, sessions: Sequence[date], known_at: datetime, window: int
) -> tuple[dict[str, Company], dict[str, list[DailyBar]], dict[str, list[Flow]]]:
    upto = sessions[-window:]
    companies = universe.at(sessions[-1])
    bars = {code: loaded.bars_at(code, upto, known_at) for code in companies}
    flows = {code: loaded.flows_at(code, upto, known_at) for code in loaded.flow_codes}
    return companies, bars, {code: f for code, f in flows.items() if f and code in companies}


# ---------- runs ----------


def _document(out: ScreenRunOut) -> dict[str, Any]:
    return to_jsonable_python(out.model_dump(mode="json"))  # type: ignore[no-any-return]


def previous_run(session: Session, rule_version: str, before: date) -> ScreenRun | None:
    """The latest judged run of a rule version for a session before `before`."""
    return session.scalars(
        select(ScreenRun)
        .where(
            ScreenRun.rule_version == rule_version,
            ScreenRun.market == "TW",
            ScreenRun.status == "judged",
            ScreenRun.session < before,
        )
        .order_by(ScreenRun.session.desc(), ScreenRun.recorded_at.desc())
        .limit(1)
    ).first()


def carried(row: ScreenRun | None) -> PreviousRun | None:
    """The watch lists a stored judged run carries."""
    if row is None:
        return None
    return previous_of(ScreenRunOut.model_validate(row.document))


def judged(session: Session, rule_version: str, day: date) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(ScreenRun)
            .where(
                ScreenRun.rule_version == rule_version,
                ScreenRun.market == "TW",
                ScreenRun.session == day,
                ScreenRun.status == "judged",
            )
        )
        or 0
    ) > 0


def _store(
    session: Session,
    out: ScreenRunOut,
    *,
    system_time: datetime,
    trigger: str,
    previous_id: UUID | None,
) -> ScreenRun:
    row = ScreenRun(
        market=out.market,
        session=out.session,
        known_at=out.known_at,
        system_time=system_time,
        rule_version=out.rule_version,
        status=out.status,
        reason=out.reason,
        previous_id=previous_id if out.status == "judged" else None,
        counts=out.counts(),
        document=_document(out),
        backfilled=system_time > out.known_at,
        trigger=trigger,
    )
    session.add(row)
    session.flush()
    return row


def _window_start(sessions: Sequence[date], index: int, window: int) -> date:
    return sessions[max(0, index - window + 1)]


def run_session(
    session: Session,
    rules: ScreenRuleSet,
    universe: Universe,
    sessions: Sequence[date],
    *,
    known_at: datetime,
    system_time: datetime | None,
    previous: PreviousRun | None,
) -> ScreenRunOut:
    """The screens at T = sessions[-1] as known at `known_at` and held at `system_time`."""
    since = _window_start(sessions, len(sessions) - 1, rules.window_sessions)
    loaded = load(
        session,
        universe,
        since=since,
        until=sessions[-1],
        known_at=known_at,
        system_time=system_time,
    )
    companies, bars, flows = _inputs_at(loaded, universe, sessions, known_at, rules.window_sessions)
    return evaluate(
        rules,
        known_at=known_at,
        companies=companies,
        bars=bars,
        sessions=sessions[-rules.window_sessions :],
        flows=flows,
        previous=previous,
        industry_basis=universe.basis,
    )


def record_live(
    session: Session,
    rules: ScreenRuleSet,
    now: datetime,
    trigger: str,
    calendar: MarketCalendar,
) -> ScreenRun | None:
    """The scheduled (or manual) run: the newest stored session not judged yet, at T = S = now;
    else a not-judged row for the calendar session whose files have not come; else None."""
    universe = universe_of(session, rules, known_at=now, system_time=None, first_known=False)
    if not universe.companies:
        return None
    today = now.astimezone(TW.zone).date()
    sessions = market_sessions(
        session,
        universe.ids.values(),
        until=today,
        known_at=now,
        system_time=None,
        since=today - timedelta(days=200),
    )
    if not sessions:
        return None
    latest = sessions[-1]
    if judged(session, rules.rule_version, latest):
        expected = [
            s.day
            for s in calendar.sessions_between(
                latest + timedelta(days=1), today - timedelta(days=1)
            )
            if s.day <= calendar.covered_until
        ]
        if not expected:
            return None
        missing = expected[-1]
        out = ScreenRunOut.model_validate(
            {
                "market": rules.market,
                "session": missing,
                "known_at": now,
                "rule_version": rules.rule_version,
                "status": "not_judged",
                "reason": (
                    f"TWSE's files of {missing} are not stored yet (the latest stored session "
                    f"is {latest}): not judged"
                ),
                "coverage": {
                    "listed": len(universe.companies),
                    "expected": 0,
                    "covered": 0,
                    "ratio": None,
                    "read": 0,
                    "unavailable": {},
                    "liquid": 0,
                },
                "industry_basis": universe.basis,
                "breadth": {},
                "movers": [],
                "movers_count": 0,
                "screens": [],
            }
        )
        return _store(session, out, system_time=now, trigger=trigger, previous_id=None)
    before = previous_run(session, rules.rule_version, latest)
    out = run_session(
        session,
        rules,
        universe,
        sessions,
        known_at=now,
        system_time=None,
        previous=carried(before),
    )
    return _store(
        session,
        out,
        system_time=now,
        trigger=trigger,
        previous_id=before.id if before else None,
    )


def backfill(
    session: Session,
    rules: ScreenRuleSet,
    system_time: datetime,
    trigger: str = "backfill",
    *,
    since: date | None = None,
    until: date | None = None,
) -> int:
    """Judge every stored session not judged yet (from the first with `min_history` sessions
    before it, or `since`) in order, each at the end of its Taipei day as held at S; the watch
    lists carried run to run. Commits each batch; returns the runs stored."""
    universe = universe_of(
        session, rules, known_at=system_time, system_time=system_time, first_known=True
    )
    if not universe.companies:
        return 0
    last = until or system_time.astimezone(TW.zone).date()
    sessions = market_sessions(
        session, universe.ids.values(), until=last, known_at=system_time, system_time=system_time
    )
    first_index = max(rules.liquidity.min_history - 1, 0)
    if since is not None:
        first_index = max(first_index, bisect.bisect_left(sessions, since))
    targets = [
        i
        for i in range(first_index, len(sessions))
        if not judged(session, rules.rule_version, sessions[i])
    ]
    stored = 0
    if not targets:
        return 0
    before = previous_run(session, rules.rule_version, sessions[targets[0]])
    previous = carried(before)
    previous_id = before.id if before else None
    for start in range(0, len(targets), BATCH_SESSIONS):
        batch = targets[start : start + BATCH_SESSIONS]
        known_last = end_of_day(sessions[batch[-1]], ZONE)
        loaded = load(
            session,
            universe,
            since=_window_start(sessions, batch[0], rules.window_sessions),
            until=sessions[batch[-1]],
            known_at=known_last,
            system_time=system_time,
        )
        for i in batch:
            upto = sessions[: i + 1]
            known_at = end_of_day(sessions[i], ZONE)
            companies, bars, flows = _inputs_at(
                loaded, universe, upto, known_at, rules.window_sessions
            )
            out = evaluate(
                rules,
                known_at=known_at,
                companies=companies,
                bars=bars,
                sessions=upto[-rules.window_sessions :],
                flows=flows,
                previous=previous,
                industry_basis=universe.basis,
            )
            row = _store(
                session, out, system_time=system_time, trigger=trigger, previous_id=previous_id
            )
            stored += 1
            if out.status == "judged":
                previous, previous_id = previous_of(out), row.id
        session.commit()
    return stored


def recompute(session: Session, row: ScreenRun) -> ScreenRunOut | None:
    """A judged run again from what was known at its T and held at its S; None for a run that
    is not judged."""
    if row.status != "judged":
        return None
    rules = stored_screen_rules(session, row.rule_version)
    if rules is None:
        return None
    first_known = str(row.document.get("industry_basis", "")).startswith("first_known")
    universe = universe_of(
        session,
        rules,
        known_at=row.known_at,
        system_time=row.system_time,
        first_known=first_known,
    )
    sessions = market_sessions(
        session,
        universe.ids.values(),
        until=row.session,
        known_at=row.known_at,
        system_time=row.system_time,
        since=row.session - timedelta(days=200),
    )
    before = session.get(ScreenRun, row.previous_id) if row.previous_id else None
    return run_session(
        session,
        rules,
        universe,
        sessions,
        known_at=row.known_at,
        system_time=row.system_time,
        previous=carried(before),
    )


def same(row: ScreenRun, out: ScreenRunOut | None) -> bool:
    return out is not None and row.document == _document(out)


def latest(session: Session, *, known_at: datetime | None = None) -> ScreenRun | None:
    """The latest judged run (of any rule version) known at `known_at`."""
    query = select(ScreenRun).where(ScreenRun.market == "TW", ScreenRun.status == "judged")
    if known_at is not None:
        query = query.where(ScreenRun.known_at <= known_at)
    return session.scalars(
        query.order_by(ScreenRun.session.desc(), ScreenRun.recorded_at.desc()).limit(1)
    ).first()


def candidates(session: Session, rules: ScreenRuleSet, universe_codes: Iterable[str]) -> list[str]:
    """The codes whose institutional flows FinMind fetches tonight (SC5): the latest judged
    run's new and watched names, then its movers, the universe left out, at most the requests
    the rules allow after the universe's own."""
    row = latest(session)
    if row is None:
        return []
    out = ScreenRunOut.model_validate(row.document)
    skip = set(universe_codes)
    cap = rules.flows.max_requests - UNIVERSE_FLOW_REQUESTS * len(skip)
    ordered: list[str] = []
    for state in ("entered", "on_watch"):
        for screen in out.screens:
            ordered += [x.code for x in screen.lines if x.state == state]
    ordered += [m.code for m in out.movers]
    found: list[str] = []
    for code in ordered:
        if code not in skip and code not in found:
            found.append(code)
    return found[: max(cap, 0)]


def watch_of(row: ScreenRun) -> Mapping[str, Sequence[Watched]]:
    found = carried(row)
    return found.watch if found else {}
