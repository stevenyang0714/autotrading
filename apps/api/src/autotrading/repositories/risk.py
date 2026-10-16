"""Paper portfolio and risk checks (M2.3, ADR-031): the journal's paper TRADEs and the market
evidence known at (T, S), the stored portfolio snapshot and risk check, in the caller's
transaction.

Every input is read as known at T and as this database held it at S (decisions by their
system time, closes and volume through `daily_bars`, splits by recorded_at, betas from the
factor snapshots recorded by S), so a stored check recomputes identically.
"""

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.api.valuation import recorded_by
from autotrading.db.models import (
    FactorSnapshot,
    PortfolioSnapshot,
    RiskCheck,
    SplitEvent,
    TradeDecision,
)
from autotrading.db.models import RiskRuleSet as RiskRuleSetRow
from autotrading.domain.convergence import AlertIn
from autotrading.domain.risk import (
    Bar,
    Check,
    Fill,
    Market,
    Portfolio,
    Proposal,
    RiskRuleSet,
    RiskRulesFile,
    Side,
    Trade,
    check,
    last_price,
    portfolio,
    standard_proposal,
)
from autotrading.domain.splits import Split
from autotrading.repositories.audit import set_actor
from autotrading.repositories.convergence import insert_alert, stored_alert_rules
from autotrading.repositories.factors import active_factor_version
from autotrading.repositories.prices import daily_bars
from autotrading.settings import get_settings

ACTOR = "rules:risk_rules"
LOOKBACK = timedelta(days=60)  # 20 sessions of volume and the last close, with holidays
Trigger = Literal["trade", "on_demand", "standard"]


def load_risk_rules(path: Path | None = None) -> RiskRulesFile:
    path = path or get_settings().resolved_config_dir() / "risk_rules.yaml"
    return RiskRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _file() -> RiskRulesFile:
    return load_risk_rules()


def active_risk_version() -> str:
    return _file().active().rule_version


def stored_risk_rules(session: Session, rule_version: str | None = None) -> RiskRuleSet | None:
    """A released risk rule set as `make migrate` registered it; None when not loaded."""
    version = rule_version or active_risk_version()
    row = session.scalars(
        select(RiskRuleSetRow).where(RiskRuleSetRow.rule_version == version)
    ).first()
    return RiskRuleSet.model_validate(row.content) if row else None


def _fill(entry_close: dict[str, Any] | None) -> Fill | None:
    stock = (entry_close or {}).get("stock")
    if not stock:
        return None
    return Fill(
        date.fromisoformat(stock["day"]),
        Decimal(str(stock["close"])),
        datetime.fromisoformat(stock["published_at"]),
    )


def trades_at(session: Session, at: datetime, system_time: datetime) -> list[Trade]:
    """The journal's paper TRADE entries known at T and recorded before S, with their exits
    (a decision written at S is the one being checked, not part of its portfolio)."""
    entries = session.scalars(
        select(TradeDecision).where(
            TradeDecision.decision == "trade",
            TradeDecision.exits_decision_id.is_(None),
            TradeDecision.known_at <= at,
            TradeDecision.system_time < system_time,
        )
    ).all()
    exits = {
        row.exits_decision_id: row
        for row in session.scalars(
            select(TradeDecision).where(
                TradeDecision.exits_decision_id.in_([e.id for e in entries]),
                TradeDecision.known_at <= at,
                TradeDecision.system_time < system_time,
            )
        )
    }
    out = []
    for entry in entries:
        fill = _fill(entry.entry_close)
        if fill is None or entry.side is None or entry.quantity is None:
            continue
        exit_row = exits.get(entry.id)
        out.append(
            Trade(
                decision_id=str(entry.id),
                ticker=entry.ticker,
                side="buy" if entry.side == "buy" else "sell",
                quantity=entry.quantity,
                entry=fill,
                known_at=entry.known_at,
                max_loss=entry.max_loss,
                exit=_fill(exit_row.entry_close) if exit_row else None,
                exit_known_at=exit_row.known_at if exit_row else None,
            )
        )
    return out


def _beta(
    session: Session, instrument_id: UUID, at: datetime, system_time: datetime
) -> Decimal | None:
    values = session.scalar(
        select(FactorSnapshot.measure_values)
        .where(
            FactorSnapshot.instrument_id == instrument_id,
            FactorSnapshot.definition_version == active_factor_version(),
            FactorSnapshot.known_at <= at,
            FactorSnapshot.recorded_at <= system_time,
        )
        .order_by(FactorSnapshot.known_at.desc())
        .limit(1)
    )
    beta = (values or {}).get("beta_252d")
    return Decimal(str(beta)) if beta is not None else None


def market_at(
    session: Session,
    rules: RiskRuleSet,
    instruments: dict[str, UUID],
    at: datetime,
    system_time: datetime,
    since: date | None,
) -> dict[str, Market]:
    """Each instrument's bars (from `since` or the lookback), splits, beta and sector at (T, S)."""
    start = at - LOOKBACK
    if since is not None:
        start = min(start, datetime.combine(since, datetime.min.time(), tzinfo=at.tzinfo))
    out = {}
    for ticker, instrument_id in instruments.items():
        bars = [
            Bar(b.bar_date, b.close, Decimal(b.volume or 0), b.feed_status, b.published_at)
            for b in daily_bars(
                session,
                instrument_id,
                "raw",
                since=start,
                until=at,
                known_at=at,
                system_time=system_time,
            )
        ]
        splits = [
            Split(s.ex_date, s.old_rate, s.new_rate)
            for s in session.scalars(
                select(SplitEvent).where(
                    SplitEvent.instrument_id == instrument_id,
                    SplitEvent.published_at <= at,
                    recorded_by(SplitEvent.recorded_at, system_time),
                )
            )
        ]
        entry = rules.sectors.get(ticker)
        out[ticker] = Market(
            ticker,
            bars,
            splits,
            _beta(session, instrument_id, at, system_time),
            entry.sector if entry else None,
        )
    return out


def book_at(
    session: Session,
    rules: RiskRuleSet,
    at: datetime,
    system_time: datetime,
    extra: dict[str, UUID] | None = None,
) -> tuple[Portfolio, dict[str, Market]]:
    """The paper portfolio at (T, S), and the market evidence it (and `extra`) read."""
    trades = trades_at(session, at, system_time)
    ids = {
        row.ticker: row.instrument_id
        for row in session.scalars(
            select(TradeDecision).where(TradeDecision.id.in_([UUID(t.decision_id) for t in trades]))
        )
    }
    ids.update(extra or {})
    since = min((t.entry.day for t in trades), default=None)
    markets = market_at(session, rules, ids, at, system_time, since)
    return portfolio(rules, at, trades, markets), markets


def snapshot_row(
    session: Session,
    rules: RiskRuleSet,
    book: Portfolio,
    at: datetime,
    system_time: datetime,
    trigger: str,
) -> PortfolioSnapshot:
    """The stored snapshot of this point (T, S, rule version), created if new."""
    session.execute(
        insert(PortfolioSnapshot)
        .values(
            known_at=at,
            system_time=system_time,
            rule_version=rules.rule_version,
            equity=book.equity,
            gross=book.gross,
            net=book.net,
            drawdown_pct=book.drawdown_pct,
            positions=len(book.positions),
            portfolio=book.model_dump(mode="json"),
            trigger=trigger,
            backfilled=system_time > at,
        )
        .on_conflict_do_nothing(constraint="uq_portfolio_snapshots_point")
    )
    return session.scalars(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.known_at == at,
            PortfolioSnapshot.system_time == system_time,
            PortfolioSnapshot.rule_version == rules.rule_version,
        )
    ).one()


def evaluate(
    session: Session,
    rules: RiskRuleSet,
    instrument_id: UUID,
    ticker: str,
    side: Side,
    quantity: Decimal | None,
    max_loss: Decimal | None,
    at: datetime,
    system_time: datetime,
) -> tuple[Check, Portfolio]:
    """A proposed trade checked at (T, S); a None quantity means the standard position."""
    book, markets = book_at(session, rules, at, system_time, {ticker: instrument_id})
    market = markets.get(ticker)
    proposal = (
        standard_proposal(rules, ticker, last_price(market, at))
        if quantity is None
        else Proposal(ticker=ticker, side=side, quantity=quantity, max_loss=max_loss)
    )
    return check(rules, at, book, proposal, market), book


def record_check(
    session: Session,
    rules: RiskRuleSet,
    instrument_id: UUID,
    ticker: str,
    side: Side,
    quantity: Decimal | None,
    max_loss: Decimal | None,
    at: datetime,
    system_time: datetime,
    trigger: Trigger,
) -> tuple[RiskCheck, Check]:
    """Check a proposed trade (the standard position when `quantity` is None) and store the
    check with its portfolio snapshot. A standard check is stored once per company and T."""
    if trigger == "standard":
        stored = session.scalars(
            select(RiskCheck).where(
                RiskCheck.instrument_id == instrument_id,
                RiskCheck.known_at == at,
                RiskCheck.rule_version == rules.rule_version,
                RiskCheck.trigger == "standard",
            )
        ).first()
        if stored is not None:
            return stored, Check.model_validate(stored.risk_check)
    else:
        set_actor(session, "web")
    result, book = evaluate(
        session, rules, instrument_id, ticker, side, quantity, max_loss, at, system_time
    )
    snapshot = snapshot_row(session, rules, book, at, system_time, trigger)
    row = RiskCheck(
        known_at=at,
        system_time=system_time,
        rule_version=rules.rule_version,
        trigger=trigger,
        instrument_id=instrument_id,
        ticker=ticker,
        side=result.proposal.side,
        quantity=result.proposal.quantity,
        max_loss=result.proposal.max_loss,
        price=result.price,
        verdict=result.verdict,
        portfolio_snapshot_id=snapshot.id,
        risk_check=result.model_dump(mode="json"),
        backfilled=system_time > at,
    )
    session.add(row)
    session.flush()
    return row, result


SCHEDULED = ("schedule", "manual", "backfill", "replay")


def drawdown_alert(
    rules: RiskRuleSet, book: Portfolio, previous: Decimal | None, snapshot_id: UUID
) -> AlertIn | None:
    """An alert when the drawdown crosses the alert threshold, either way (ADR-031 R4)."""
    limit = rules.drawdown_alert_pct
    now = book.drawdown_pct >= limit
    was = previous is not None and previous >= limit
    if now == was:
        return None
    title = (
        f"Paper portfolio drawdown reached {book.drawdown_pct}% (alert at {limit}%)"
        if now
        else f"Paper portfolio drawdown back within {limit}% ({book.drawdown_pct}%)"
    )
    return AlertIn(
        kind="portfolio",
        level=1 if now else 0,
        previous_level=1 if was else 0,
        direction="up" if now else "down",
        title=title,
        source_key=f"portfolio:{snapshot_id}",
        known_at=book.known_at,
        evidence=[
            {
                "table": "portfolio_snapshots",
                "id": str(snapshot_id),
                "label": f"Equity {book.equity} USD, {book.drawdown_pct}% below its peak of "
                f"{book.peak_equity} USD",
            }
        ],
    )


def record_portfolio(
    session: Session, rules: RiskRuleSet, at: datetime, system_time: datetime, trigger: str
) -> PortfolioSnapshot:
    """Store the paper portfolio at T (daily, R4) and, when its drawdown crossed the alert
    threshold since the previous scheduled snapshot, a portfolio alert under the active alert
    rules (if they ask for it)."""
    set_actor(session, ACTOR)
    previous = session.scalar(
        select(PortfolioSnapshot.drawdown_pct)
        .where(
            PortfolioSnapshot.rule_version == rules.rule_version,
            PortfolioSnapshot.trigger.in_(SCHEDULED),
            PortfolioSnapshot.known_at < at,
        )
        .order_by(PortfolioSnapshot.known_at.desc())
        .limit(1)
    )
    book, _ = book_at(session, rules, at, system_time)
    snapshot = snapshot_row(session, rules, book, at, system_time, trigger)
    alert_rules = stored_alert_rules(session)
    found = drawdown_alert(rules, book, previous, snapshot.id)
    if (
        found is not None
        and alert_rules is not None
        and "drawdown" in alert_rules.portfolio_events
        and alert_rules.risk_rule_version == rules.rule_version
    ):
        insert_alert(session, alert_rules, None, None, found, system_time, None, system_time > at)
    return snapshot


def recompute(session: Session, row: RiskCheck) -> Check | None:
    """A stored risk check recomputed with its own T, S, rule version and trade."""
    rules = stored_risk_rules(session, row.rule_version)
    if rules is None:
        return None
    stored = Check.model_validate(row.risk_check)
    proposal = stored.proposal
    result, _ = evaluate(
        session,
        rules,
        row.instrument_id,
        row.ticker,
        proposal.side,
        proposal.quantity,
        proposal.max_loss,
        row.known_at,
        row.system_time,
    )
    return result


def checks(
    session: Session, at: datetime, tickers: Iterable[str] | None = None, limit: int = 50
) -> list[RiskCheck]:
    query = select(RiskCheck).where(RiskCheck.known_at <= at)
    if tickers is not None:
        query = query.where(RiskCheck.ticker.in_(list(tickers)))
    return list(session.scalars(query.order_by(RiskCheck.known_at.desc()).limit(limit)))


def set_rules_actor(session: Session) -> None:
    set_actor(session, ACTOR)
