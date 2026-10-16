"""Opportunity Radar candidates (M2.4, ADR-032 Q3): what the rules flag as known at T, read from
stored rows; nothing is evaluated or stored on request.

- Companies whose latest convergence assessment at or before T is L3 Trade Candidate or L4
  Execution Ready, for strategy S1, with every level check and the items behind it.
- The ETFs of the S3 rotation target in force at T, with their trend readings and the stress
  state that allowed them.
- The market's stress state and quadrant at T, as context.

Long only (no short data, OD-5). No score and no ranking across instruments (P2-3, KI-1, errata
E3): companies are listed by level, then ticker; ETFs in the rotation's universe order.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on

from autotrading.api.alerts import CompanyLevel, company_level
from autotrading.api.data_health import SessionDep
from autotrading.api.instruments import universe_equities
from autotrading.api.research import KnownAt
from autotrading.api.rotation import latest_rotation
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import ConvergenceAssessment, RegimeAssessment
from autotrading.domain.registries import STRATEGIES
from autotrading.domain.rotation import EtfReading, Rotation
from autotrading.domain.signals import BUYBACK_STRATEGY
from autotrading.repositories.convergence import active_alert_version, stored_alert_rules
from autotrading.repositories.regime import active_regime_version
from autotrading.repositories.rotation import active_rotation_version, stored_rotation_rules

router = APIRouter(tags=["candidates"])

STRATEGY_NAMES = {s.id: s.name for s in STRATEGIES}
CANDIDATE_LEVELS = (3, 4)  # L3 Trade Candidate, L4 Execution Ready
LONG_ONLY = (
    "Long only (no short data, OD-5). What the rules flag as known at the date, not a buy list "
    "and not ranked: companies at L3 or L4 (S1) and the ETFs of the S3 rotation target. "
    "Thresholds are defaults, unvalidated (OD-7)."
)


class MarketContext(BaseModel):
    regime_id: UUID
    known_at: datetime
    rule_version: str
    stress: str | None
    quadrant: str | None


class CompanyCandidate(BaseModel):
    ticker: str
    strategy_id: str
    strategy: str
    alert_rule_version: str
    buyback_rule_version: str
    convergence: CompanyLevel


class EtfCandidate(BaseModel):
    ticker: str
    strategy_id: str
    strategy: str
    weight_pct: Decimal
    rotation_id: UUID
    rotation_rule_version: str
    regime_rule_version: str
    factor_definition_version: str
    set_at: datetime  # when the target in force was set
    reason: str  # of the assessment in force at T: month_start, defensive_switch or carried
    stress: str | None  # at T
    reading: EtfReading  # as read at T


class OpportunityCandidatesOut(BaseModel):
    known_at: datetime
    context: MarketContext | None
    companies: list[CompanyCandidate]
    etfs: list[EtfCandidate]
    detail: str = LONG_ONLY


def _context(session: SessionDep, at: datetime) -> MarketContext | None:
    row = session.scalars(
        select(RegimeAssessment)
        .where(
            RegimeAssessment.rule_version == active_regime_version(),
            RegimeAssessment.known_at <= at,
        )
        .order_by(RegimeAssessment.known_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return MarketContext(
        regime_id=row.id,
        known_at=row.known_at,
        rule_version=row.rule_version,
        stress=row.stress,
        quadrant=row.quadrant,
    )


def _companies(session: SessionDep, at: datetime) -> list[CompanyCandidate]:
    version = active_alert_version()
    rules = stored_alert_rules(session, version)
    if rules is None:
        return []
    rows = session.scalars(
        select(ConvergenceAssessment)
        .where(
            ConvergenceAssessment.rule_version == version,
            ConvergenceAssessment.known_at <= at,
        )
        .ext(distinct_on(ConvergenceAssessment.instrument_id))
        .order_by(ConvergenceAssessment.instrument_id, ConvergenceAssessment.known_at.desc())
    ).all()
    universe = {t for t, _, _ in universe_equities(session)}
    found = [
        CompanyCandidate(
            ticker=r.ticker,
            strategy_id=BUYBACK_STRATEGY,
            strategy=STRATEGY_NAMES[BUYBACK_STRATEGY],
            alert_rule_version=version,
            buyback_rule_version=rules.buyback_rule_version,
            convergence=company_level(r),
        )
        for r in rows
        if r.level in CANDIDATE_LEVELS and r.ticker in universe
    ]
    found.sort(key=lambda c: (-(c.convergence.level or 0), c.ticker))
    return found


def _etfs(session: SessionDep, at: datetime) -> list[EtfCandidate]:
    rules = stored_rotation_rules(session, active_rotation_version())
    row = latest_rotation(session, at)
    if rules is None or row is None:
        return []
    rotation = Rotation.model_validate(row.assessment)
    if not rotation.target or rotation.set_at is None:
        return []
    readings = {r.symbol: r for r in rotation.readings}
    return [
        EtfCandidate(
            ticker=h.symbol,
            strategy_id="S3",
            strategy=STRATEGY_NAMES["S3"],
            weight_pct=h.weight_pct,
            rotation_id=row.id,
            rotation_rule_version=rules.rule_version,
            regime_rule_version=rules.regime_rule_version,
            factor_definition_version=rules.factor_definition_version,
            set_at=rotation.set_at,
            reason=rotation.reason,
            stress=rotation.stress,
            reading=readings[h.symbol],
        )
        for h in rotation.target
        if h.symbol in readings
    ]


@router.get("/candidates")
def candidates(session: SessionDep, known_at: KnownAt = None) -> OpportunityCandidatesOut:
    at = known_at_or_now(session, known_at)
    return OpportunityCandidatesOut(
        known_at=at,
        context=_context(session, at),
        companies=_companies(session, at),
        etfs=_etfs(session, at),
    )
