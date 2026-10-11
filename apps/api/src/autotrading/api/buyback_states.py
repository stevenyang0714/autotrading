"""Buyback states (M1.4b, ADR-025, errata E7): evaluation, storage and the read API.

Evaluation (`evaluate`): one company at a time T, as the database held it at system_time S,
under one rule set (config/buyback_rules.yaml, synced to buyback_rule_sets). Every input is
read as known at T and recorded by S (facts, closes, splits, 8-K statements of one extractor
version, press releases, the 10-year Treasury yield and the assumption version saved by then),
so the same T, S, rule version and extractor version always give the same assessment; it is
stored whole in buyback_state_assignments (`record_assignment`).

- Daily (scheduled at 11:00 SGT, after the SEC refresh): T = S = now.
- Backfill (B6): every month end since 2021 with one S for the run, marked backfilled.

Read API (the stored assignments; nothing is evaluated on request):
- GET /buybacks: the Corporate Actions dashboard. Per universe equity, the latest assignment
  at or before T under the active rule set, its state history and the announcements known at
  T; the active rule set with its thresholds for the threshold review (P1-9).
- GET /buybacks/rules: every released rule set.
No state triggers a trade (02 §5); TRADE-READY is unreachable in Phase 1 (P1-4).
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

import yaml
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.adapters.sec.refresh import EIGHT_K_SINCE
from autotrading.api.buyback_announcements import (
    AnnouncementEvent,
    announcement_sources,
    event_out,
)
from autotrading.api.data_health import SessionDep
from autotrading.api.fair_value import (
    FAIR_VALUE_METRICS,
    chosen_version,
    dcf_snapshot,
    risk_free_at,
)
from autotrading.api.instruments import FactView, issuer_chain, universe_equities
from autotrading.api.research import KnownAt, ResearchPeriod
from autotrading.api.valuation import (
    VALUATION_METRICS,
    InputOut,
    MarketView,
    filing_forms,
    input_out,
    known_at_or_now,
    market_view,
)
from autotrading.db.models import (
    BuybackRuleSet,
    BuybackStateAssignment,
    FinancialFact,
    Instrument,
)
from autotrading.domain.buyback import BUYBACK_METRICS, SharesAt, events
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION
from autotrading.domain.buyback_states import (
    Assessment,
    Comparison,
    DcfContext,
    Evidence,
    Level,
    Measure,
    RuleSet,
    RulesFile,
    ScoreRule,
    StateId,
    StateRules,
    Status,
    assess,
)
from autotrading.domain.fair_value import month_ends, multiple_history, snapshots
from autotrading.domain.fundamentals import merge_by_precedence
from autotrading.domain.valuation import Close, Input
from autotrading.repositories.facts import row_key, visible_in_system_time
from autotrading.repositories.prices import daily_bars, instruments_by_symbol
from autotrading.settings import get_settings

router = APIRouter(tags=["buyback-states"])

STATE_METRICS = tuple(dict.fromkeys((*BUYBACK_METRICS, *FAIR_VALUE_METRICS)))
HISTORY_YEARS = 6  # closes for five fiscal year ends, the latest quarter and the FCF yields
BENCHMARK_DAYS = 60  # calendar days of benchmark closes: more than the return window
Trigger = Literal["schedule", "manual", "backfill", "replay"]
BACKFILL_SINCE = date(2021, 1, 1)  # B6: month ends from the first year of 8-Ks (B2)


# ---------- the rule file ----------


def load_rules(path: Path | None = None) -> RulesFile:
    path = path or get_settings().resolved_config_dir() / "buyback_rules.yaml"
    return RulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _rules() -> RulesFile:
    return load_rules()


class RuleSetNotLoadedError(LookupError):
    """The rule version is not in buyback_rule_sets: run `make migrate`."""


def stored_rule_set(session: Session, rule_version: str) -> RuleSet:
    """A released rule set as `make migrate` registered it (never changed since)."""
    row = session.scalars(
        select(BuybackRuleSet).where(BuybackRuleSet.rule_version == rule_version)
    ).first()
    if row is None:
        raise RuleSetNotLoadedError(f"buyback rule set {rule_version} is not loaded: make migrate")
    return RuleSet.model_validate(row.content)


# ---------- output ----------


class ConditionOut(BaseModel):
    condition_id: str
    level: Level
    status: Status
    value: Decimal | None
    unit: str
    threshold: Decimal | None
    comparison: Comparison | None
    detail: str
    inputs: list[InputOut]
    announcements: list[AnnouncementEvent]


class LevelOut(BaseModel):
    level: Level
    status: Status
    rule: str


class ComponentOut(BaseModel):
    component: str
    weight: int
    measure: Measure
    zero: Decimal
    full: Decimal
    value: Decimal | None
    score: Decimal | None  # 0-100
    detail: str | None
    inputs: list[InputOut]


class ScoreOut(BaseModel):
    total: Decimal | None  # 0-100; unavailable when any component is (B8)
    detail: str | None
    label: str  # "default weights, unvalidated"
    components: list[ComponentOut]


class AssessmentOut(BaseModel):
    """Everything an assignment stores: recomputing it gives the same document."""

    state: StateId
    levels: list[LevelOut]
    conditions: list[ConditionOut]
    score: ScoreOut
    period: ResearchPeriod | None  # the latest period the conditions read
    assumption_version: int | None  # of the DCF; None: the built-in default
    extractor_version: str
    issuers: list[str]  # the issuer chain read (entity ids)


class StateAssignmentOut(BaseModel):
    ticker: str
    known_at: datetime
    system_time: datetime
    rule_version: str
    backfilled: bool
    trigger: Trigger
    recorded_at: datetime
    assessment: AssessmentOut


class StatePoint(BaseModel):
    known_at: datetime
    state: StateId
    score: Decimal | None
    backfilled: bool


class RuleSetOut(BaseModel):
    rule_version: str
    status: Literal["active", "retired"]
    approved: date
    note: str
    content_sha256: str
    loaded_at: datetime
    period_end_shares: SharesAt  # the share count of a period end's market cap (B12)
    states: StateRules
    score: ScoreRule


class CompanyStates(BaseModel):
    ticker: str
    name: str
    assignment: StateAssignmentOut | None  # the latest at or before T
    history: list[StatePoint]  # oldest first
    announcements: list[AnnouncementEvent]  # known at T, newest first


class BuybackStatesOut(BaseModel):
    known_at: datetime
    rule_set: RuleSetOut
    companies: list[CompanyStates]


def _inputs(values: Iterable[Input[FactView]], forms: dict[str, str]) -> list[InputOut]:
    return [input_out(i, forms) for i in values]


def assessment_out(
    session: Session,
    assessment: Assessment[FactView],
    dcf: DcfContext,
    extractor_version: str,
    issuers: Sequence[object],
) -> AssessmentOut:
    forms = filing_forms(
        session,
        [
            *(f for c in assessment.conditions for i in c.inputs for f in i.sources),
            *(f for c in assessment.score.components for i in c.inputs for f in i.sources),
        ],
    )
    window = assessment.period
    score = assessment.score
    return AssessmentOut(
        state=assessment.state,
        levels=[LevelOut(level=r.level, status=r.status, rule=r.rule) for r in assessment.levels],
        conditions=[
            ConditionOut(
                condition_id=c.condition_id,
                level=c.level,
                status=c.status,
                value=c.value,
                unit=c.unit,
                threshold=c.threshold,
                comparison=c.comparison,
                detail=c.detail,
                inputs=_inputs(c.inputs, forms),
                announcements=[event_out(e) for e in c.events],
            )
            for c in assessment.conditions
        ],
        score=ScoreOut(
            total=score.total,
            detail=score.detail,
            label=score.label,
            components=[
                ComponentOut(
                    component=c.component,
                    weight=c.weight,
                    measure=c.measure,
                    zero=c.zero,
                    full=c.full,
                    value=c.value,
                    score=c.score,
                    detail=c.detail,
                    inputs=_inputs(c.inputs, forms),
                )
                for c in score.components
            ],
        ),
        period=ResearchPeriod(kind=window.kind, period_start=window.start, period_end=window.end)
        if window
        else None,
        assumption_version=dcf.assumption_version,
        extractor_version=extractor_version,
        issuers=[str(i) for i in issuers],
    )


# ---------- evaluation ----------


def _fcf_yield_history(
    session: Session,
    chain: Sequence[UUID],
    view: MarketView,
    at: datetime,
    system_time: datetime | None,
    years: int,
) -> list[tuple[date, Decimal]]:
    """FCF yield at each month end of the last `years` years, each from the fact versions
    public then and the close known then (as the relative valuation, ADR-023)."""
    versions = session.scalars(
        select(FinancialFact).where(
            FinancialFact.entity_id.in_(chain),
            FinancialFact.metric_id.in_(VALUATION_METRICS),
            FinancialFact.published_at <= at,
            visible_in_system_time(FinancialFact, system_time),
        )
    ).all()
    since = date(at.year - years, at.month, 1)
    points = (
        (point, [FactView(f) for f in merge_by_precedence(known, chain)])
        for point, known in snapshots(
            versions,
            month_ends(since, at),
            row_key,
            lambda f: f.published_at,
            lambda f: f.recorded_at,
        )
    )
    return multiple_history(points, view.closes, view.dated_splits)["fcf_yield"]


def _benchmark(
    session: Session, symbol: str, at: datetime, system_time: datetime | None
) -> list[Close]:
    instrument = instruments_by_symbol(session, [symbol]).get(symbol)
    if instrument is None:
        return []
    bars = daily_bars(
        session,
        instrument,
        "raw",
        since=at - timedelta(days=BENCHMARK_DAYS),
        until=at,
        known_at=at,
        system_time=system_time,
    )
    return [Close(b.bar_date, b.close, b.feed_status, b.published_at) for b in bars]


def evaluate(
    session: Session,
    instrument: Instrument,
    at: datetime,
    system_time: datetime | None,
    rule_set: RuleSet,
    extractor_version: str = EXTRACTOR_VERSION,
) -> AssessmentOut:
    """The assessment of one company at T as the database held it at `system_time`."""
    assert instrument.entity_id is not None
    chain = issuer_chain(session, instrument.entity_id)
    view = market_view(
        session,
        instrument,
        chain.order,
        at,
        STATE_METRICS,
        bars_since=datetime(at.year - HISTORY_YEARS, 1, 1, tzinfo=UTC),
        system_time=system_time,
    )
    chosen = chosen_version(session, instrument.id, None, at, system_time)
    snapshot = dcf_snapshot(view, chosen.parameters, risk_free_at(session, at, system_time), at)
    base = snapshot.result.scenarios.get("base")
    price = view.price.close.close if view.price.status == "ok" and view.price.close else None
    dcf = DcfContext(
        status=snapshot.result.status,
        detail=snapshot.comparison_detail,
        base_per_share=base.per_share if base else None,
        price=price,
        margin_of_safety=snapshot.result.margin_of_safety,
        assumption_version=chosen.version,
    )
    rules = rule_set.states
    evidence = Evidence[FactView](
        at=at,
        facts=view.facts,
        closes=view.closes,
        splits=view.splits,
        price=view.price,
        events=events(
            announcement_sources(
                session, instrument, chain.order, at, system_time, extractor_version
            ),
            at,
        ),
        announcements_since=EIGHT_K_SINCE,
        # Without a valuation price at T there is no FCF yield to compare with its history.
        fcf_yield_history=_fcf_yield_history(
            session,
            chain.order,
            view,
            at,
            system_time,
            rules.high_conviction.fcf_yield_history_years,
        )
        if view.price.status == "ok"
        else [],
        dcf=dcf,
        benchmark_closes=_benchmark(session, rules.trade_ready.benchmark, at, system_time),
    )
    return assessment_out(session, assess(rule_set, evidence), dcf, extractor_version, chain.order)


def record_assignment(
    session: Session,
    ticker: str,
    instrument: Instrument,
    at: datetime,
    system_time: datetime,
    rule_set: RuleSet,
    trigger: Trigger,
) -> bool:
    """Evaluate and store; False when this company, T and rule version are stored already."""
    exists = session.scalar(
        select(BuybackStateAssignment.id).where(
            BuybackStateAssignment.instrument_id == instrument.id,
            BuybackStateAssignment.known_at == at,
            BuybackStateAssignment.rule_version == rule_set.rule_version,
        )
    )
    if exists is not None:
        return False
    found = evaluate(session, instrument, at, system_time, rule_set)
    inserted = session.execute(
        insert(BuybackStateAssignment)
        .values(
            instrument_id=instrument.id,
            ticker=ticker,
            known_at=at,
            system_time=system_time,
            rule_version=rule_set.rule_version,
            extractor_version=found.extractor_version,
            state=found.state,
            score=found.score.total,
            assessment=found.model_dump(mode="json"),
            backfilled=system_time > at,
            trigger=trigger,
        )
        .on_conflict_do_nothing(constraint="uq_buyback_state_assignments_instrument_known_at_rule")
        .returning(BuybackStateAssignment.id)
    ).first()
    return inserted is not None


def evaluate_universe(
    session: Session,
    at: datetime,
    system_time: datetime,
    trigger: Trigger,
    rule_set: RuleSet | None = None,
) -> int:
    """Every universe equity at T under the active rule set (by default); returns how many
    assignments were stored. Commits once per company."""
    rule_set = rule_set or stored_rule_set(session, _rules().active().rule_version)
    stored = 0
    for ticker, instrument, _ in universe_equities(session):
        stored += record_assignment(session, ticker, instrument, at, system_time, rule_set, trigger)
        session.commit()
    return stored


# ---------- read API ----------


def assignment_out(row: BuybackStateAssignment) -> StateAssignmentOut:
    return StateAssignmentOut(
        ticker=row.ticker,
        known_at=row.known_at,
        system_time=row.system_time,
        rule_version=row.rule_version,
        backfilled=row.backfilled,
        trigger=row.trigger,  # type: ignore[arg-type]
        recorded_at=row.recorded_at,
        assessment=AssessmentOut.model_validate(row.assessment),
    )


def stored_states(
    session: Session, instrument_id: object, at: datetime, rule_version: str
) -> tuple[StateAssignmentOut | None, list[StatePoint]]:
    """The latest assignment at or before T and every earlier one, under one rule version."""
    rows = session.scalars(
        select(BuybackStateAssignment)
        .where(
            BuybackStateAssignment.instrument_id == instrument_id,
            BuybackStateAssignment.rule_version == rule_version,
            BuybackStateAssignment.known_at <= at,
        )
        .order_by(BuybackStateAssignment.known_at)
    ).all()
    history = [
        StatePoint(
            known_at=r.known_at,
            state=r.state,  # type: ignore[arg-type]
            score=r.score,
            backfilled=r.backfilled,
        )
        for r in rows
    ]
    return (assignment_out(rows[-1]) if rows else None), history


def active_rule_version() -> str:
    return _rules().active().rule_version


def _rule_set_out(row: BuybackRuleSet, file: RulesFile) -> RuleSetOut:
    content = RuleSet.model_validate(row.content)
    entry = next((r for r in file.rule_sets if r.rule_version == row.rule_version), None)
    return RuleSetOut(
        rule_version=row.rule_version,
        status=entry.status if entry else "retired",
        approved=content.approved,
        note=content.note,
        content_sha256=row.content_sha256,
        loaded_at=row.loaded_at,
        period_end_shares=content.period_end_shares,
        states=content.states,
        score=content.score,
    )


@router.get("/buybacks/rules")
def buyback_rules(session: SessionDep) -> list[RuleSetOut]:
    file = _rules()
    rows = sorted(
        session.scalars(select(BuybackRuleSet)),
        key=lambda r: tuple(int(n) for n in r.rule_version.split(".")),
        reverse=True,
    )
    return [_rule_set_out(row, file) for row in rows]  # newest version first


@router.get("/buybacks")
def buyback_states(session: SessionDep, known_at: KnownAt = None) -> BuybackStatesOut:
    at = known_at_or_now(session, known_at)
    file = _rules()
    version = file.active().rule_version
    row = session.scalars(
        select(BuybackRuleSet).where(BuybackRuleSet.rule_version == version)
    ).one()
    companies = []
    for ticker, instrument, entity in universe_equities(session):
        latest, history = stored_states(session, instrument.id, at, version)
        chain = issuer_chain(session, entity.id)
        companies.append(
            CompanyStates(
                ticker=ticker,
                name=entity.name,
                assignment=latest,
                history=history,
                announcements=[
                    event_out(e)
                    for e in events(announcement_sources(session, instrument, chain.order, at), at)
                ],
            )
        )
    return BuybackStatesOut(known_at=at, rule_set=_rule_set_out(row, file), companies=companies)
