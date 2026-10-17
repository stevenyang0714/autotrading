"""Backtests (M2.5, ADR-033): the stored runs as known at T, and the factor overlap between the
strategies read from them. Nothing is run on request; performance is withheld (OD-7).

- `GET /backtests`: each strategy's latest run at or before T under the active backtest rules,
  and the overlap (shared holdings of S1 and S4, each strategy's sectors and beta).
- `GET /backtests/{id}`: one stored run.
- `GET /backtests/rules`, `GET /momentum/rules`: the released rule sets.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import BacktestRuleSet as BacktestRuleSetRow
from autotrading.db.models import BacktestRun
from autotrading.db.models import MomentumRuleSet as MomentumRuleSetRow
from autotrading.domain.backtest import WITHHELD_REASON, Rebalance, Run
from autotrading.repositories.backtest import (
    active_backtest_version,
    latest_runs,
    load_backtest_rules,
    load_momentum_rules,
)

router = APIRouter(tags=["backtests"])

PAPER_RESEARCH = (
    "Backtests on stored point-in-time data, filled at the next session close, with costs. "
    + WITHHELD_REASON
)


class StoredRun(BaseModel):
    id: UUID
    known_at: datetime
    system_time: datetime
    trigger: str
    performance_reported: bool
    run: Run


class StrategyOverlap(BaseModel):
    strategy_id: str
    rebalances: int
    average_beta: Decimal | None
    sectors: dict[str, Decimal]  # average target weight per sector


class Overlap(BaseModel):
    """Factor overlap (01 §30, S4's unlock): how much S4 holds what S1 holds on the same days,
    and each strategy's average sectors and beta."""

    shared_months: int  # S4 targets with an S1 target in force
    shared_pct: Decimal | None  # average share of S4's companies also held by S1
    strategies: list[StrategyOverlap]


class BacktestsOut(BaseModel):
    known_at: datetime
    rule_version: str
    runs: list[StoredRun]
    overlap: Overlap | None
    detail: str = PAPER_RESEARCH


class BacktestRuleSetOut(BaseModel):
    rule_version: str
    status: Literal["active", "retired"]
    released: date
    content: dict[str, Any]
    content_sha256: str


def _q(value: Decimal, quantum: str = "0.01") -> Decimal:
    return value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP)


def stored(row: BacktestRun) -> StoredRun:
    return StoredRun(
        id=row.id,
        known_at=row.known_at,
        system_time=row.system_time,
        trigger=row.trigger,
        performance_reported=row.performance_reported,
        run=Run.model_validate(row.document),
    )


def _in_force(rebalances: list[Rebalance], day: date) -> Rebalance | None:
    found = None
    for rebalance in rebalances:
        if rebalance.fill_day is not None and rebalance.fill_day <= day:
            found = rebalance
    return found


def overlap(runs: dict[str, Run]) -> Overlap | None:
    if not runs:
        return None
    shares: list[Decimal] = []
    s1, s4 = runs.get("S1"), runs.get("S4")
    if s1 is not None and s4 is not None:
        for rebalance in s4.rebalances:
            if rebalance.fill_day is None or not rebalance.target:
                continue
            other = _in_force(s1.rebalances, rebalance.fill_day)
            if other is None:
                continue
            common = set(rebalance.target) & set(other.target)
            shares.append(Decimal(len(common)) / Decimal(len(rebalance.target)) * 100)
    strategies: list[StrategyOverlap] = []
    for strategy_id in sorted(runs):
        filled = [r for r in runs[strategy_id].rebalances if r.fill_day is not None]
        betas = [r.beta for r in filled if r.beta is not None]
        sectors: dict[str, Decimal] = {}
        for rebalance in filled:
            for sector, weight in rebalance.sectors.items():
                sectors[sector] = sectors.get(sector, Decimal(0)) + weight
        strategies.append(
            StrategyOverlap(
                strategy_id=strategy_id,
                rebalances=len(filled),
                average_beta=_q(sum(betas, Decimal(0)) / len(betas), "0.001") if betas else None,
                sectors={s: _q(w / len(filled)) for s, w in sorted(sectors.items())}
                if filled
                else {},
            )
        )
    return Overlap(
        shared_months=len(shares),
        shared_pct=_q(sum(shares, Decimal(0)) / len(shares)) if shares else None,
        strategies=strategies,
    )


@router.get("/backtests/rules")
def backtest_rules(session: SessionDep) -> list[BacktestRuleSetOut]:
    status = {r.rule_version: r.status for r in load_backtest_rules().rule_sets}
    return [
        BacktestRuleSetOut(
            rule_version=row.rule_version,
            status=status.get(row.rule_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in session.scalars(
            select(BacktestRuleSetRow).order_by(BacktestRuleSetRow.loaded_at.desc())
        )
    ]


@router.get("/momentum/rules")
def momentum_rules(session: SessionDep) -> list[BacktestRuleSetOut]:
    status = {r.rule_version: r.status for r in load_momentum_rules().rule_sets}
    return [
        BacktestRuleSetOut(
            rule_version=row.rule_version,
            status=status.get(row.rule_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in session.scalars(
            select(MomentumRuleSetRow).order_by(MomentumRuleSetRow.loaded_at.desc())
        )
    ]


@router.get("/backtests")
def backtests(session: SessionDep, known_at: KnownAt = None) -> BacktestsOut:
    at = known_at_or_now(session, known_at)
    version = active_backtest_version()
    rows = latest_runs(session, version, at)
    runs = [stored(r) for r in rows]
    return BacktestsOut(
        known_at=at,
        rule_version=version,
        runs=runs,
        overlap=overlap({r.run.strategy_id: r.run for r in runs}),
    )


@router.get("/backtests/{run_id}")
def backtest(session: SessionDep, run_id: UUID) -> StoredRun:
    row = session.get(BacktestRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such backtest run")
    return stored(row)
