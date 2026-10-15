"""Paper portfolio and risk checks (M2.3, ADR-031; 02 §20). Paper only: no order exists.

- `GET /portfolio`: the paper portfolio as known at T (the journal's open paper TRADEs marked
  at the closes known then): positions, exposures, sectors, the equity curve and drawdown, and
  each limit of the active risk rules.
- `GET /risk/checks`, `GET /risk/checks/{id}`: stored risk checks (journal TRADEs, on-demand
  tries and the daily standard positions), each limit with its value and threshold.
- `POST /risk/checks`: try a paper trade against the limits now; the check is stored and
  audited, no decision is recorded.
- `GET /risk/rules`: the released risk rule sets.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now, universe_equity
from autotrading.db.models import RiskCheck
from autotrading.db.models import RiskRuleSet as RiskRuleSetRow
from autotrading.domain.risk import Check, Limits, Portfolio, RiskRuleSet, Standard
from autotrading.repositories.risk import (
    book_at,
    load_risk_rules,
    record_check,
    stored_risk_rules,
)

router = APIRouter(tags=["risk"])

PAPER_ONLY = (
    "PAPER ONLY: a notional portfolio built from the journal's paper decisions. No order is "
    "placed or prepared; limits are defaults, unvalidated (OD-7)."
)


class RiskCheckOut(BaseModel):
    id: UUID
    known_at: datetime
    system_time: datetime
    rule_version: str
    trigger: Literal["trade", "on_demand", "standard"]
    ticker: str
    verdict: Literal["pass", "veto"]
    backfilled: bool
    portfolio_snapshot_id: UUID
    check: Check


class RiskChecksOut(BaseModel):
    known_at: datetime
    checks: list[RiskCheckOut]


class RulesOut(BaseModel):
    rule_version: str
    capital: Decimal
    limits: Limits
    drawdown_alert_pct: Decimal
    standard: Standard
    unlimited_sectors: list[str]
    sectors: dict[str, str]  # ticker -> sector


class PortfolioOut(BaseModel):
    known_at: datetime
    rules: RulesOut
    portfolio: Portfolio
    vetoes: int  # risk checks vetoed by T (journal and on-demand)
    detail: str = PAPER_ONLY


class RiskRuleSetOut(BaseModel):
    rule_version: str
    status: Literal["active", "retired"]
    released: date
    content: dict[str, Any]
    content_sha256: str


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=10)
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, le=10**9)
    max_loss: Decimal | None = Field(default=None, gt=0)


def _rules(session: Session) -> RiskRuleSet:
    rules = stored_risk_rules(session)
    if rules is None:
        raise HTTPException(status_code=503, detail="risk rules are not loaded (make migrate)")
    return rules


def check_out(row: RiskCheck) -> RiskCheckOut:
    return RiskCheckOut(
        id=row.id,
        known_at=row.known_at,
        system_time=row.system_time,
        rule_version=row.rule_version,
        trigger=cast(Literal["trade", "on_demand", "standard"], row.trigger),
        ticker=row.ticker,
        verdict=cast(Literal["pass", "veto"], row.verdict),
        backfilled=row.backfilled,
        portfolio_snapshot_id=row.portfolio_snapshot_id,
        check=Check.model_validate(row.risk_check),
    )


def rules_out(rules: RiskRuleSet) -> RulesOut:
    return RulesOut(
        rule_version=rules.rule_version,
        capital=rules.capital,
        limits=rules.limits,
        drawdown_alert_pct=rules.drawdown_alert_pct,
        standard=rules.standard,
        unlimited_sectors=rules.unlimited_sectors,
        sectors={ticker: entry.sector for ticker, entry in rules.sectors.items()},
    )


@router.get("/risk/rules")
def risk_rules(session: SessionDep) -> list[RiskRuleSetOut]:
    file = load_risk_rules()
    status = {r.rule_version: r.status for r in file.rule_sets}
    return [
        RiskRuleSetOut(
            rule_version=row.rule_version,
            status=status.get(row.rule_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in session.scalars(select(RiskRuleSetRow).order_by(RiskRuleSetRow.loaded_at.desc()))
    ]


@router.get("/portfolio")
def paper_portfolio(session: SessionDep, known_at: KnownAt = None) -> PortfolioOut:
    at = known_at_or_now(session, known_at)
    now = session.execute(select(func.now())).scalar_one()
    rules = _rules(session)
    book, _ = book_at(session, rules, at, now)
    vetoes = session.scalar(
        select(func.count())
        .select_from(RiskCheck)
        .where(
            RiskCheck.known_at <= at,
            RiskCheck.verdict == "veto",
            RiskCheck.trigger != "standard",
        )
    )
    return PortfolioOut(known_at=at, rules=rules_out(rules), portfolio=book, vetoes=vetoes or 0)


@router.get("/risk/checks")
def risk_checks(
    session: SessionDep,
    known_at: KnownAt = None,
    ticker: str | None = None,
    trigger: Literal["trade", "on_demand", "standard"] | None = None,
    limit: int = Query(default=30, ge=1, le=200),
) -> RiskChecksOut:
    at = known_at_or_now(session, known_at)
    query = select(RiskCheck).where(RiskCheck.known_at <= at)
    if ticker:
        query = query.where(RiskCheck.ticker == ticker.upper())
    if trigger:
        query = query.where(RiskCheck.trigger == trigger)
    rows = session.scalars(
        query.order_by(RiskCheck.known_at.desc(), RiskCheck.recorded_at.desc()).limit(limit)
    )
    return RiskChecksOut(known_at=at, checks=[check_out(row) for row in rows])


@router.get("/risk/checks/{check_id}")
def risk_check(check_id: UUID, session: SessionDep) -> RiskCheckOut:
    row = session.get(RiskCheck, check_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no risk check {check_id}")
    return check_out(row)


@router.post("/risk/checks", status_code=201)
def try_check(body: CheckIn, session: SessionDep) -> RiskCheckOut:
    """Try a paper trade against the active limits now (T = S = now). Stored and audited; no
    decision is recorded and nothing is sent anywhere."""
    instrument = universe_equity(session, body.ticker)
    rules = _rules(session)
    now = session.execute(select(func.now())).scalar_one()
    row, _ = record_check(
        session,
        rules,
        instrument.id,
        body.ticker.upper(),
        body.side,
        body.quantity,
        body.max_loss,
        now,
        now,
        "on_demand",
    )
    session.commit()
    return check_out(row)
