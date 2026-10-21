"""The context of a pushed message (M3.0c, ADR-038): plain values read from the stored rows an
alert came from, as known at its T (`known_at`) and held at its S (`system_time`), for
`domain.delivery.chinese`. Nothing here decides anything: it reads.

- S4 and S3 targets: the companies or ETFs a new target adds, drops and keeps (the assessment
  and its previous target), each with its conditions as read.
- A company's level: the convergence checks and the company.
- Every company: P/E and FCF yield against its own monthly history (the factor page's read),
  the DCF margin and buyback state of its latest buyback assignment.
- Market stress: the flags that were on; the market's stress state and quadrant at T; the
  rule's review rhythm and the median holding period of its latest backtest (not a return).

Any id that does not resolve leaves the message without details (the evidence labels instead).
"""

import logging
import statistics
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.api.factors import instrument_factors
from autotrading.db.models import (
    Alert,
    BacktestRun,
    BuybackStateAssignment,
    ConvergenceAssessment,
    MomentumAssessment,
    RegimeAssessment,
    RotationAssessment,
)
from autotrading.domain.delivery import Check, Condition, Context, Facts
from autotrading.repositories.convergence import stored_alert_rules
from autotrading.repositories.labels import label
from autotrading.repositories.prices import instruments_by_symbol
from autotrading.repositories.regime import active_regime_version
from autotrading.repositories.risk import stored_risk_rules

logger = logging.getLogger(__name__)

SESSIONS_PER_MONTH = Decimal(21)
REVIEW = {
    "momentum": "每個紐約月份第一次評估時調整（S4）",
    "rotation": "每個紐約月份第一次評估時調整，壓力升到高或危機時立即轉防守（S3）",
    "level_change": "每天依庫藏股狀態與市場確認重新評估（S1）",
}
STRATEGY = {"momentum": "S4", "rotation": "S3", "level_change": "S1"}


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _sectors(session: Session, risk_version: str | None) -> dict[str, str]:
    rules = stored_risk_rules(session, risk_version) if risk_version else None
    return {s: e.sector for s, e in rules.sectors.items()} if rules else {}


def _conditions(reading: Mapping[str, Any] | None, key: str) -> tuple[Condition, ...]:
    if not reading:
        return ()
    return tuple(
        Condition(
            measure=str(c["measure"]),
            value=_decimal(c.get("value")),
            threshold=Decimal(str(c.get("threshold", 0))),
            passed=c.get("status") == "pass",
        )
        for c in reading.get(key) or []
    )


def company_facts(
    session: Session,
    symbol: str,
    at: datetime,
    system_time: datetime,
    sectors: Mapping[str, str],
    *,
    weight: Decimal | None = None,
    conditions: tuple[Condition, ...] = (),
    buyback_rule_version: str | None = None,
) -> Facts:
    """Who the symbol is and what the stored rows say about it at (T, S)."""
    found = label(symbol, dict(sectors))
    pe = pe_rank = fcf = fcf_rank = None
    try:
        factors = instrument_factors(symbol, session, at)
    except HTTPException:
        factors = None
    if factors is not None:
        measures = {m.measure_id: m for m in factors.measures}
        if (m := measures.get("pe_ratio_ttm")) is not None and m.value is not None:
            pe, pe_rank = m.value, m.percentile
        if (m := measures.get("fcf_yield")) is not None and m.value is not None:
            fcf, fcf_rank = m.value, m.percentile
    state = margin = None
    instrument_id = instruments_by_symbol(session, [symbol]).get(symbol)
    if instrument_id is not None and buyback_rule_version:
        assignment = session.scalars(
            select(BuybackStateAssignment)
            .where(
                BuybackStateAssignment.instrument_id == instrument_id,
                BuybackStateAssignment.rule_version == buyback_rule_version,
                BuybackStateAssignment.known_at <= at,
                BuybackStateAssignment.recorded_at <= system_time,
            )
            .order_by(BuybackStateAssignment.known_at.desc())
            .limit(1)
        ).first()
        if assignment is not None:
            state = assignment.state
            for c in assignment.assessment.get("conditions", []):
                if c.get("condition_id") == "high_conviction.dcf_discount":
                    margin = _decimal(c.get("value"))
    return Facts(
        symbol=symbol,
        zh=found.zh,
        label=found.short(),
        about=found.about_zh,
        weight=weight,
        conditions=conditions,
        pe=pe,
        pe_percentile=pe_rank,
        fcf_yield=fcf,
        fcf_percentile=fcf_rank,
        dcf_margin=margin,
        buyback_state=state,
    )


def _market(session: Session, at: datetime, system_time: datetime) -> tuple[str | None, str | None]:
    row = session.scalars(
        select(RegimeAssessment)
        .where(
            RegimeAssessment.rule_version == active_regime_version(),
            RegimeAssessment.known_at <= at,
            RegimeAssessment.recorded_at <= system_time,
        )
        .order_by(RegimeAssessment.known_at.desc())
        .limit(1)
    ).first()
    return (row.stress, row.quadrant) if row else (None, None)


def _holding_months(session: Session, strategy: str, at: datetime) -> Decimal | None:
    """The median holding period of the closed positions of the strategy's latest backtest run
    known at T, in months of 21 sessions (a holding time, not a return)."""
    run = session.scalars(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == strategy, BacktestRun.known_at <= at)
        .order_by(BacktestRun.known_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return None
    closed = [p["sessions"] for p in run.document.get("positions", []) if p.get("exit")]
    if not closed:
        return None
    return Decimal(str(statistics.median(closed))) / SESSIONS_PER_MONTH


def _targets(
    session: Session,
    sectors: Mapping[str, str],
    at: datetime,
    system_time: datetime,
    now: Mapping[str, Decimal],
    was: Mapping[str, Decimal],
    readings: Mapping[str, Mapping[str, Any]],
    key: str,
    order: Iterable[str],
    buyback_rule_version: str | None,
) -> tuple[tuple[Facts, ...], tuple[Facts, ...], tuple[Facts, ...]]:
    def facts(symbol: str, weight: Decimal | None) -> Facts:
        return company_facts(
            session,
            symbol,
            at,
            system_time,
            sectors,
            weight=weight,
            conditions=_conditions(readings.get(symbol), key),
            buyback_rule_version=buyback_rule_version,
        )

    ranked = [s for s in order]
    ranked += sorted(s for s in {*now, *was} if s not in ranked)
    entered = tuple(facts(s, now[s]) for s in ranked if s in now and s not in was)
    left = tuple(facts(s, None) for s in ranked if s in was and s not in now)
    kept = tuple(
        Facts(
            symbol=s, zh=label(s).zh, label=label(s, dict(sectors)).short(), about="", weight=now[s]
        )
        for s in ranked
        if s in now and s in was
    )
    return entered, left, kept


def alert_context(session: Session, row: Alert) -> Context | None:
    """The context of one stored alert, or None when its rows do not resolve."""
    try:
        return _context(session, row)
    except (KeyError, LookupError, ValueError, TypeError):
        logger.warning("No message details for alert %s (%s)", row.id, row.kind)
        return None


def _context(session: Session, row: Alert) -> Context | None:
    rules = stored_alert_rules(session, row.rule_version)
    if rules is None:
        return None
    at, held = row.known_at, row.system_time
    sectors = _sectors(session, rules.risk_rule_version or "0.1.0")
    stress, quadrant = _market(session, at, held)
    common: dict[str, Any] = {"stress": stress, "quadrant": quadrant}
    if row.kind in STRATEGY:
        common["review"] = REVIEW[row.kind]
        common["holding_months"] = _holding_months(session, STRATEGY[row.kind], at)
    evidence_id = _uuid(row.evidence[0].get("id")) if row.evidence else None
    if row.kind == "momentum":
        found = session.get(MomentumAssessment, evidence_id) if evidence_id else None
        if found is None:
            return None
        before = session.get(MomentumAssessment, found.previous_id) if found.previous_id else None
        readings = {r["symbol"]: r for r in found.assessment.get("readings", [])}
        entered, left, kept = _targets(
            session,
            sectors,
            at,
            held,
            {s: Decimal(w) for s, w in (found.target or {}).items()},
            {s: Decimal(w) for s, w in ((before.target if before else None) or {}).items()},
            readings,
            "conditions",
            readings,
            rules.buyback_rule_version,
        )
        return Context(entered=entered, left=left, kept=kept, **common)
    if row.kind == "rotation":
        found_rotation = session.get(RotationAssessment, evidence_id) if evidence_id else None
        if found_rotation is None:
            return None
        before_rotation = (
            session.get(RotationAssessment, found_rotation.previous_id)
            if found_rotation.previous_id
            else None
        )
        readings = {r["symbol"]: r for r in found_rotation.assessment.get("readings", [])}
        previous = (before_rotation.target if before_rotation else None) or {}
        entered, left, kept = _targets(
            session,
            sectors,
            at,
            held,
            {s: Decimal(w) for s, w in (found_rotation.target or {}).items()},
            {s: Decimal(w) for s, w in previous.items()},
            readings,
            "trend",
            readings,
            None,
        )
        return Context(entered=entered, left=left, kept=kept, **common)
    if row.kind == "level_change" and row.ticker:
        assessment = session.get(ConvergenceAssessment, row.assessment_id)
        checks = tuple(
            Check(
                level=int(c["level"]),
                passed={"pass": True, "fail": False}.get(str(c.get("status"))),
                detail=str(c.get("detail") or ""),
            )
            for c in (assessment.assessment.get("levels", []) if assessment else [])
            if int(c["level"]) >= 2
        )
        company = company_facts(
            session, row.ticker, at, held, sectors, buyback_rule_version=rules.buyback_rule_version
        )
        return Context(company=company, checks=checks, **common)
    if row.kind == "regime":
        if evidence_id is None or session.get(RegimeAssessment, evidence_id) is None:
            return None
        flags = tuple(e["label"] for e in row.evidence[1:] if e.get("label"))
        return Context(flags=flags, **common)
    return Context(**common)
