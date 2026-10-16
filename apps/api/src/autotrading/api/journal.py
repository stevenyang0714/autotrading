"""Paper journal (M1.6, ADR-027): Thesis Cards with their evidence, paper TRADE and NO TRADE
decisions, paper performance and replay.

- Writes are at T = system time = the database's now (no backdating). The client sends evidence
  references only; each is read here as known at (T, S) and stored as a snapshot (J2).
- Cards and decisions are append-only and audited (actor `web`). A card change is a new version;
  an exit is a new decision pointing at its entry.
- Nothing here or anywhere sends an order: decisions are paper records, checked by the database
  (mode `paper`, no broker; P1-6), and requests cannot carry broker fields.
- A replay reads every evidence item, the valuation and each decision's closes again at the
  stored (T, S) and reports each identical, different or missing (acceptance 1).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from autotrading.api.buyback_states import active_rule_version
from autotrading.api.data_health import SessionDep
from autotrading.api.fair_value import (
    ACTOR,
    FAIR_VALUE_METRICS,
    chosen_version,
    dcf_snapshot,
    risk_free_at,
)
from autotrading.api.instruments import issuer_chain
from autotrading.api.research import KnownAt
from autotrading.api.valuation import (
    known_at_or_now,
    market_view,
    universe_equity,
)
from autotrading.db.models import (
    BuybackStateAssignment,
    Filing,
    FilingBuybackStatement,
    FilingGuidanceStatement,
    FinancialFact,
    Instrument,
    NewsItem,
    NewsMention,
    PriceBar,
    SignalRecord,
    SplitEvent,
    ThesisCard,
    TradeDecision,
)
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION
from autotrading.domain.fundamentals import merge_by_precedence
from autotrading.domain.guidance import GUIDANCE_VERSION
from autotrading.domain.journal import (
    MAX_CATALYSTS,
    MAX_EVIDENCE,
    MIN_EVIDENCE,
    EvidenceKind,
    Mark,
    NoTradeReason,
    ReplayStatus,
    Side,
    compare,
    paper_return,
)
from autotrading.domain.splits import Split
from autotrading.repositories.audit import set_actor
from autotrading.repositories.facts import as_of_query
from autotrading.repositories.prices import instruments_by_symbol
from autotrading.repositories.risk import record_check, stored_risk_rules

router = APIRouter(tags=["journal"])

USER = "steven"  # one user (errata E1); the API binds to localhost only
BENCHMARK = "SPY"
STALE_AFTER = timedelta(days=7)  # a last close older than this at T is flagged stale
PAPER_ONLY = (
    "Paper journal: decisions are records, never orders. Returns use end-of-day closes only "
    "(no costs, slippage, dividends or fills)."
)
CANDIDATE_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capex",
    "share_repurchases",
    "shares_outstanding",
)
CANDIDATE_FILINGS = ("10-K", "10-Q", "8-K")


def _json(value: Any) -> Any:
    return to_jsonable_python(value)


# ---------- requests ----------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceRef(_Strict):
    """One system row: by id, or a close by its session day."""

    kind: EvidenceKind
    id: UUID | None = None
    day: date | None = None
    note: str | None = Field(default=None, max_length=200)  # why it matters; not evidence

    @model_validator(mode="after")
    def _one_reference(self) -> "EvidenceRef":
        by_day = self.kind == "price_close"
        if (self.day is not None) != by_day or (self.id is not None) == by_day:
            raise ValueError("a price_close takes a day; every other kind takes an id")
        return self

    def ref(self) -> dict[str, str]:
        return {"day": self.day.isoformat()} if self.day else {"id": str(self.id)}


class Catalyst(_Strict):
    description: str = Field(min_length=1, max_length=200)
    expected: date | None = None


class CardContent(_Strict):
    thesis: str = Field(min_length=1, max_length=400)
    evidence: list[EvidenceRef] = Field(min_length=MIN_EVIDENCE, max_length=MAX_EVIDENCE)
    catalysts: list[Catalyst] = Field(default_factory=list, max_length=MAX_CATALYSTS)
    invalidation: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    signal_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _distinct_evidence(self) -> "CardContent":
        keys = [(e.kind, tuple(e.ref().items())) for e in self.evidence]
        if len(set(keys)) != len(keys):
            raise ValueError("an evidence row is listed twice")
        return self


class NewDecision(_Strict):
    decision: Literal["trade", "no_trade"]
    side: Side | None = None
    quantity: Decimal | None = Field(default=None, gt=0, le=10**9)
    order_type: Literal["market", "limit"] | None = None
    limit_price: Decimal | None = Field(default=None, gt=0)
    max_loss: Decimal | None = Field(default=None, gt=0)
    no_trade_reason: NoTradeReason | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _consistent(self) -> "NewDecision":
        if self.decision == "trade":
            if self.side is None or self.quantity is None or self.order_type is None:
                raise ValueError("a TRADE needs a side, a quantity and an order type")
            if self.max_loss is None:  # M2.3 (ADR-031 R1): the risk check needs it
                raise ValueError("a TRADE states its maximum loss in USD")
            if self.no_trade_reason is not None:
                raise ValueError("a TRADE has no NO TRADE reason")
            if (self.order_type == "limit") != (self.limit_price is not None):
                raise ValueError("a limit price goes with a limit order, and only then")
        else:
            trade_fields = (self.side, self.quantity, self.order_type, self.limit_price)
            if any(v is not None for v in (*trade_fields, self.max_loss)):
                raise ValueError(
                    "a NO TRADE has no side, quantity, order type, limit price or maximum loss"
                )
            if self.no_trade_reason is None:
                raise ValueError("a NO TRADE needs a reason")
            if self.no_trade_reason == "other" and not self.note:
                raise ValueError("the reason `other` needs a note")
        return self


class NewEntry(CardContent):
    ticker: str = Field(min_length=1, max_length=10)
    decision: NewDecision


class ExitIn(_Strict):
    note: str | None = Field(default=None, max_length=1000)


# ---------- responses ----------


class EvidenceOut(BaseModel):
    kind: EvidenceKind
    ref: dict[str, str]
    label: str
    summary: str
    note: str | None
    published_at: datetime  # when it became public (a state: its T)
    source_url: str | None
    snapshot: dict[str, Any]  # the row as known at (T, S)


class ValuationSnapshot(BaseModel):
    status: str  # the DCF's: ok, unavailable, not_meaningful
    detail: str | None
    assumption_version: int | None  # None: the built-in default
    base_per_share: Decimal | None
    price: Decimal | None
    price_day: date | None
    margin_of_safety: Decimal | None  # percent
    implied_upside: Decimal | None  # percent


class CloseOut(BaseModel):
    symbol: str
    day: date
    close: Decimal
    published_at: datetime
    feed_status: str  # end_of_day; fixture for recorded demo data
    stale: bool  # older than a week at the decision or viewing time
    row_id: str


class Closes(BaseModel):
    """The last end-of-day closes known at a decision's T: the stock's and SPY's."""

    stock: CloseOut | None
    benchmark: CloseOut | None


class PerformanceOut(BaseModel):
    status: Literal["ok", "unavailable"]
    detail: str | None
    open: bool  # a TRADE without an exit known at the viewing time
    entry: CloseOut | None
    mark: CloseOut | None  # the last close known at the viewing time, or the exit's
    split_factor: Decimal
    entry_basis: Decimal | None  # the entry close on the mark's split basis
    return_pct: Decimal | None  # signed by side; a NO TRADE: the stock's move, unsigned
    pnl: Decimal | None  # USD
    benchmark: str
    benchmark_return_pct: Decimal | None
    relative: Decimal | None  # percentage points
    max_loss_breached: bool | None


class JournalDecisionOut(BaseModel):
    id: UUID
    thesis_card_id: UUID
    card_version: int
    decision: Literal["trade", "no_trade"]
    side: Side | None
    quantity: Decimal | None
    order_type: str | None
    limit_price: Decimal | None
    max_loss: Decimal | None
    no_trade_reason: NoTradeReason | None
    note: str | None
    exits_decision_id: UUID | None
    exited_by: UUID | None  # the exit decision known at the viewing time
    closes: Closes | None
    strategy_id: str | None
    signal_ids: list[str]
    mode: Literal["paper"]
    approval_state: str
    known_at: datetime
    system_time: datetime
    performance: PerformanceOut | None  # entries and NO TRADEs; None for an exit


class CardOut(BaseModel):
    id: UUID
    card_id: UUID
    version: int
    ticker: str
    known_at: datetime
    system_time: datetime
    thesis: str
    evidence: list[EvidenceOut]
    catalysts: list[Catalyst]
    invalidation: str
    valuation: ValuationSnapshot
    signal_ids: list[str]
    notes: str | None
    author: str
    created_at: datetime


class VersionOut(BaseModel):
    id: UUID
    version: int
    known_at: datetime


class JournalCardOut(BaseModel):
    known_at: datetime  # the viewing time
    card: CardOut  # the requested version, or the latest known at the viewing time
    versions: list[VersionOut]
    decisions: list[JournalDecisionOut]
    detail: str = PAPER_ONLY


class JournalRow(BaseModel):
    card_id: UUID
    ticker: str
    version: int  # the latest known at the viewing time
    thesis: str
    known_at: datetime  # of the first version
    signal_ids: list[str]
    decision: JournalDecisionOut | None  # the first decision
    exit: JournalDecisionOut | None


class JournalOut(BaseModel):
    known_at: datetime
    entries: list[JournalRow]
    detail: str = PAPER_ONLY


class CandidatesOut(BaseModel):
    ticker: str
    known_at: datetime
    candidates: list[EvidenceOut]


class ReplayItem(BaseModel):
    kind: str
    label: str
    status: ReplayStatus
    changed: list[str]
    stored: dict[str, Any]
    again: dict[str, Any] | None


class ReplayOut(BaseModel):
    card_id: UUID
    version: int
    known_at: datetime
    system_time: datetime
    identical: bool
    evidence: list[ReplayItem]
    valuation: ReplayItem
    decisions: list[ReplayItem]


# ---------- evidence: each kind read as known at (T, S) ----------


@dataclass(frozen=True)
class Subject:
    """The company a card is about: its instrument and issuer chain (ADR-014)."""

    ticker: str
    instrument: Instrument
    chain: list[UUID]


def subject(session: Session, ticker: str) -> Subject:
    instrument = universe_equity(session, ticker)
    assert instrument.entity_id is not None
    return Subject(ticker.upper(), instrument, issuer_chain(session, instrument.entity_id).order)


def _evidence(
    kind: EvidenceKind,
    ref: dict[str, str],
    label: str,
    summary: str,
    published_at: datetime,
    source_url: str | None,
    snapshot: dict[str, Any],
) -> EvidenceOut:
    return EvidenceOut(
        kind=kind,
        ref=ref,
        label=label,
        summary=summary,
        note=None,
        published_at=published_at,
        source_url=source_url,
        snapshot=_json(snapshot),
    )


def _period(row: FinancialFact) -> str:
    if row.period_start is None:
        return f"at {row.period_end}"
    return f"{row.period_start} to {row.period_end}"


def _fact(row: FinancialFact) -> EvidenceOut:
    return _evidence(
        "financial_fact",
        {"id": str(row.id)},
        f"{row.metric_id} {_period(row)}",
        f"{row.value} {row.unit}",
        row.published_at,
        row.source_url,
        {
            "row_id": row.id,
            "metric_id": row.metric_id,
            "value": row.value,
            "unit": row.unit,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "fiscal_period": row.fiscal_period,
            "accession_id": row.accession_id,
            "published_at": row.published_at,
            "version": row.version,
        },
    )


def _filing(row: Filing) -> EvidenceOut:
    return _evidence(
        "filing",
        {"id": str(row.id)},
        f"{row.form} {row.accession_number}",
        f"filed {row.filing_date}" + (f", period {row.report_date}" if row.report_date else ""),
        row.published_at,
        row.source_url,
        {
            "row_id": row.id,
            "form": row.form,
            "accession_number": row.accession_number,
            "filing_date": row.filing_date,
            "accepted_at": row.accepted_at,
            "report_date": row.report_date,
            "items": row.items,
            "published_at": row.published_at,
        },
    )


def _buyback_statement(row: FilingBuybackStatement) -> EvidenceOut:
    return _evidence(
        "buyback_statement",
        {"id": str(row.id)},
        f"Buyback {row.kind.replace('_', ' ')} ({row.document_type} {row.accession_number})",
        row.sentence,
        row.published_at,
        row.source_url,
        {
            "row_id": row.id,
            "accession_number": row.accession_number,
            "document_type": row.document_type,
            "kind": row.kind,
            "amount": row.amount,
            "remaining_amount": row.remaining_amount,
            "stated_date": row.stated_date,
            "sentence": row.sentence,
            "extractor_version": row.extractor_version,
            "published_at": row.published_at,
        },
    )


def _guidance_statement(row: FilingGuidanceStatement) -> EvidenceOut:
    return _evidence(
        "guidance_statement",
        {"id": str(row.id)},
        f"Guidance {row.metric.replace('_', ' ')} ({row.document_type} {row.accession_number})",
        row.sentence,
        row.published_at,
        row.source_url,
        {
            "row_id": row.id,
            "accession_number": row.accession_number,
            "document_type": row.document_type,
            "metric": row.metric,
            "low": row.low,
            "high": row.high,
            "unit": row.unit,
            "period_text": row.period_text,
            "adjusted": row.adjusted,
            "sentence": row.sentence,
            "extractor_version": row.extractor_version,
            "published_at": row.published_at,
        },
    )


def _buyback_state(row: BuybackStateAssignment) -> EvidenceOut:
    return _evidence(
        "buyback_state",
        {"id": str(row.id)},
        f"Buyback state under rules {row.rule_version}",
        row.state.replace("_", " ").upper()
        + (f", score {row.score}" if row.score is not None else ""),
        row.known_at,
        None,
        {
            "row_id": row.id,
            "rule_version": row.rule_version,
            "state": row.state,
            "score": row.score,
            "known_at": row.known_at,
            "system_time": row.system_time,
            "backfilled": row.backfilled,
        },
    )


def _news(row: NewsItem) -> EvidenceOut:
    return _evidence(
        "news",
        {"id": str(row.id)},
        f"{row.publisher}: {row.title}",
        row.snippet or row.title,
        row.published_at,
        row.url,
        {
            "row_id": row.id,
            "title": row.title,
            "publisher": row.publisher,
            "url": row.url,
            "kind": row.kind,
            "published_at": row.published_at,
        },
    )


def _close(row: PriceBar) -> EvidenceOut:
    return _evidence(
        "price_close",
        {"day": row.bar_date.isoformat()},
        f"{row.symbol} close {row.bar_date}",
        f"{row.close} USD",
        row.published_at,
        row.source_url,
        {
            "row_id": row.id,
            "day": row.bar_date,
            "close": row.close,
            "volume": row.volume,
            "feed_status": row.feed_status,
            "published_at": row.published_at,
            "version": row.version,
        },
    )


def resolve(
    session: Session,
    who: Subject,
    kind: EvidenceKind,
    ref: dict[str, str],
    at: datetime,
    system_time: datetime,
) -> EvidenceOut | None:
    """The row `ref` names, as known at T and as the database held it at S; None when it is
    not a row of this company visible then."""
    if kind == "price_close":
        bar = session.scalars(
            as_of_query(PriceBar, known_at=at, system_time=system_time).where(
                PriceBar.instrument_id == who.instrument.id,
                PriceBar.adjustment == "raw",
                PriceBar.bar_date == date.fromisoformat(ref["day"]),
            )
        ).first()
        return _close(bar) if bar else None
    row_id = UUID(ref["id"])
    if kind == "financial_fact":
        fact = session.get(FinancialFact, row_id)
        if fact is None or fact.entity_id not in who.chain:
            return None
        key = [getattr(FinancialFact, c) == getattr(fact, c) for c in FinancialFact.__fact_key__]
        visible = session.scalars(
            as_of_query(FinancialFact, known_at=at, system_time=system_time).where(*key)
        ).first()
        return _fact(visible) if visible else None
    if kind == "buyback_state":
        state = session.get(BuybackStateAssignment, row_id)
        if (
            state is None
            or state.instrument_id != who.instrument.id
            or state.known_at > at
            or state.recorded_at > system_time
        ):
            return None
        return _buyback_state(state)
    if kind == "news":
        item = session.get(NewsItem, row_id)
        mentioned = session.scalar(
            select(NewsMention.id).where(
                NewsMention.news_item_id == row_id,
                NewsMention.instrument_id == who.instrument.id,
                NewsMention.recorded_at <= system_time,
            )
        )
        if item is None or mentioned is None or not _public(item, at, system_time):
            return None
        return _news(item)
    if kind == "filing":
        filing = session.get(Filing, row_id)
        if filing is None or filing.entity_id not in who.chain:
            return None
        return _filing(filing) if _public(filing, at, system_time) else None
    if kind == "buyback_statement":
        bought = session.get(FilingBuybackStatement, row_id)
        if bought is None or bought.entity_id not in who.chain:
            return None
        return _buyback_statement(bought) if _public(bought, at, system_time) else None
    guided = session.get(FilingGuidanceStatement, row_id)
    if guided is None or guided.entity_id not in who.chain:
        return None
    return _guidance_statement(guided) if _public(guided, at, system_time) else None


def _public(
    row: Filing | FilingBuybackStatement | FilingGuidanceStatement | NewsItem,
    at: datetime,
    system_time: datetime,
) -> bool:
    return row.published_at <= at and row.recorded_at <= system_time


def candidates(session: Session, who: Subject, at: datetime) -> list[EvidenceOut]:
    """What a card can cite for this company at T: the latest annual, quarterly and point
    values of the main metrics, recent filings, buyback and guidance statements, the latest
    buyback state, recent news and the last close."""
    found: list[EvidenceOut] = []
    facts = merge_by_precedence(
        session.scalars(
            as_of_query(FinancialFact, known_at=at).where(
                FinancialFact.entity_id.in_(who.chain),
                FinancialFact.metric_id.in_(CANDIDATE_METRICS),
            )
        ).all(),
        who.chain,
    )
    for metric in CANDIDATE_METRICS:
        rows = [f for f in facts if f.metric_id == metric]
        for fits in (_annual, _quarter, _instant):
            fitting = [f for f in rows if fits(f)]
            if fitting:
                found.append(_fact(max(fitting, key=lambda f: (f.period_end, f.published_at))))
    found += [
        _filing(row)
        for row in session.scalars(
            select(Filing)
            .where(
                Filing.entity_id.in_(who.chain),
                Filing.form.in_(CANDIDATE_FILINGS),
                Filing.published_at <= at,
            )
            .order_by(Filing.published_at.desc())
            .limit(8)
        )
    ]
    found += [
        _buyback_statement(row)
        for row in session.scalars(
            select(FilingBuybackStatement)
            .where(
                FilingBuybackStatement.entity_id.in_(who.chain),
                FilingBuybackStatement.extractor_version == EXTRACTOR_VERSION,
                FilingBuybackStatement.published_at <= at,
            )
            .order_by(FilingBuybackStatement.published_at.desc())
            .limit(5)
        )
    ]
    found += [
        _guidance_statement(row)
        for row in session.scalars(
            select(FilingGuidanceStatement)
            .where(
                FilingGuidanceStatement.entity_id.in_(who.chain),
                FilingGuidanceStatement.extractor_version == GUIDANCE_VERSION,
                FilingGuidanceStatement.published_at <= at,
            )
            .order_by(FilingGuidanceStatement.published_at.desc())
            .limit(5)
        )
    ]
    state = session.scalars(
        select(BuybackStateAssignment)
        .where(
            BuybackStateAssignment.instrument_id == who.instrument.id,
            BuybackStateAssignment.rule_version == active_rule_version(),
            BuybackStateAssignment.known_at <= at,
        )
        .order_by(BuybackStateAssignment.known_at.desc())
        .limit(1)
    ).first()
    if state is not None:
        found.append(_buyback_state(state))
    found += [
        _news(row)
        for row in session.scalars(
            select(NewsItem)
            .join(NewsMention, NewsMention.news_item_id == NewsItem.id)
            .where(NewsMention.instrument_id == who.instrument.id, NewsItem.published_at <= at)
            .order_by(NewsItem.published_at.desc())
            .limit(10)
        ).unique()
    ]
    bar = last_bar(session, who.instrument.id, at, None)
    if bar is not None:
        found.append(_close(bar))
    return found


def _days(row: FinancialFact) -> int | None:
    return None if row.period_start is None else (row.period_end - row.period_start).days


def _annual(row: FinancialFact) -> bool:
    days = _days(row)
    return days is not None and 340 <= days <= 380


def _quarter(row: FinancialFact) -> bool:
    days = _days(row)
    return days is not None and 80 <= days <= 100


def _instant(row: FinancialFact) -> bool:
    return row.period_start is None


# ---------- valuation and closes at (T, S) ----------


def valuation_at(
    session: Session, who: Subject, at: datetime, system_time: datetime
) -> ValuationSnapshot:
    """The base DCF against the price, as the fair value page would have shown it at T with
    the data held at S and the assumption version saved by then (ADR-023)."""
    view = market_view(
        session, who.instrument, who.chain, at, FAIR_VALUE_METRICS, system_time=system_time
    )
    chosen = chosen_version(session, who.instrument.id, None, at, system_time)
    snapshot = dcf_snapshot(view, chosen.parameters, risk_free_at(session, at, system_time), at)
    base = snapshot.result.scenarios.get("base")
    close = view.price.close if view.price.status == "ok" else None
    return ValuationSnapshot(
        status=snapshot.result.status,
        detail=snapshot.comparison_detail or snapshot.result.detail,
        assumption_version=chosen.version,
        base_per_share=base.per_share if base else None,
        price=close.close if close else None,
        price_day=close.day if close else None,
        margin_of_safety=snapshot.result.margin_of_safety,
        implied_upside=snapshot.result.implied_upside,
    )


def last_bar(
    session: Session, instrument_id: UUID, at: datetime, system_time: datetime | None
) -> PriceBar | None:
    """The last raw daily bar whose close is known at T, as held at S (any age)."""
    known = as_of_query(PriceBar, known_at=at, system_time=system_time).where(
        PriceBar.instrument_id == instrument_id,
        PriceBar.adjustment == "raw",
        PriceBar.bar_time <= at,
    )
    row = aliased(PriceBar, known.subquery())
    return session.scalars(select(row).order_by(row.bar_time.desc()).limit(1)).first()


def last_close(
    session: Session,
    instrument_id: UUID | None,
    symbol: str,
    at: datetime,
    system_time: datetime | None,
) -> CloseOut | None:
    """The last end-of-day close known at T, as held at S, with its day and whether it is
    stale (older than STALE_AFTER at T) or recorded demo data."""
    bar = last_bar(session, instrument_id, at, system_time) if instrument_id else None
    if bar is None:
        return None
    return CloseOut(
        symbol=symbol,
        day=bar.bar_date,
        close=bar.close,
        published_at=bar.published_at,
        feed_status=bar.feed_status,
        stale=at - bar.published_at > STALE_AFTER,
        row_id=str(bar.id),
    )


def closes_at(session: Session, who: Subject, at: datetime, system_time: datetime | None) -> Closes:
    benchmark = instruments_by_symbol(session, [BENCHMARK]).get(BENCHMARK)
    return Closes(
        stock=last_close(session, who.instrument.id, who.ticker, at, system_time),
        benchmark=last_close(session, benchmark, BENCHMARK, at, system_time),
    )


def _splits(session: Session, instrument_id: UUID, at: datetime) -> list[Split]:
    return [
        Split(s.ex_date, s.old_rate, s.new_rate)
        for s in session.scalars(
            select(SplitEvent).where(
                SplitEvent.instrument_id == instrument_id, SplitEvent.published_at <= at
            )
        )
    ]


# ---------- writes ----------


def write_time() -> datetime | None:
    """T of a write. None, always in production: the database's now (no backdating, ADR-027).
    Tests pin an earlier T to cite recorded closes; S is always the database's now."""
    return None


WriteTime = Annotated[datetime | None, Depends(write_time)]


@dataclass(frozen=True)
class Times:
    at: datetime  # T
    now: datetime  # S, the database's now


def _times(session: Session, pinned: datetime | None) -> Times:
    now = session.execute(select(func.now())).scalar_one()
    return Times(pinned or now, now)


def _resolve_all(
    session: Session, who: Subject, refs: Sequence[EvidenceRef], when: Times
) -> list[dict[str, Any]]:
    stored = []
    for i, ref in enumerate(refs, start=1):
        found = resolve(session, who, ref.kind, ref.ref(), when.at, when.now)
        if found is None:
            raise HTTPException(
                status_code=422,
                detail=f"evidence {i} ({ref.kind} {ref.ref()}) is not a row of {who.ticker} "
                "known now",
            )
        stored.append(found.model_copy(update={"note": ref.note}).model_dump(mode="json"))
    return stored


def _signals(session: Session, who: Subject, ids: Sequence[UUID], now: datetime) -> list[str]:
    found = set(
        session.scalars(
            select(SignalRecord.id).where(
                SignalRecord.id.in_(ids),
                SignalRecord.instrument_id == who.instrument.id,
                SignalRecord.generated_at <= now,
            )
        )
    )
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"not a signal of {who.ticker} known now: {missing}"
        )
    return [str(i) for i in dict.fromkeys(ids)]


def _strategy(session: Session, signal_ids: Sequence[str]) -> str | None:
    """The strategy of the cited signals when they share one (Phase 1: S1)."""
    strategies = set(
        session.scalars(
            select(SignalRecord.strategy_id).where(SignalRecord.id.in_(map(UUID, signal_ids)))
        )
    )
    return strategies.pop() if len(strategies) == 1 else None


def _card_row(
    session: Session,
    who: Subject,
    content: CardContent,
    card_id: UUID,
    version: int,
    when: Times,
) -> ThesisCard:
    return ThesisCard(
        card_id=card_id,
        version=version,
        instrument_id=who.instrument.id,
        ticker=who.ticker,
        known_at=when.at,
        system_time=when.now,
        thesis=content.thesis,
        evidence=_resolve_all(session, who, content.evidence, when),
        catalysts=[c.model_dump(mode="json") for c in content.catalysts],
        invalidation=content.invalidation,
        valuation=valuation_at(session, who, when.at, when.now).model_dump(mode="json"),
        signal_ids=_signals(session, who, content.signal_ids, when.at),
        notes=content.notes,
        author=ACTOR,
        user_id=USER,
    )


def _commit(session: Session, conflict: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=conflict) from exc


def _paper(**fields: Any) -> TradeDecision:
    """A paper decision row: paper mode, no broker, one user (the database checks them too); a
    TRADE entry carries its passed risk check (ADR-031, P2-7), other decisions none."""
    return TradeDecision(
        mode="paper",
        broker=None,
        approval_state="recorded",
        user_id=USER,
        **{"risk_check_id": None, "portfolio_snapshot_id": None, **fields},
    )


def _risk_check(
    session: Session, who: Subject, choice: NewDecision, when: Times
) -> tuple[UUID, UUID]:
    """Check a TRADE entry against the active risk rules at (T, S). A veto is stored and
    committed, then the entry is refused (422) with every limit that failed."""
    rules = stored_risk_rules(session)
    if rules is None:
        raise HTTPException(status_code=503, detail="risk rules are not loaded (make migrate)")
    assert choice.side is not None and choice.quantity is not None
    row, result = record_check(
        session,
        rules,
        who.instrument.id,
        who.ticker,
        choice.side,
        choice.quantity,
        choice.max_loss,
        when.at,
        when.now,
        "trade",
    )
    if result.verdict == "veto":
        session.commit()  # the veto is recorded (ADR-031)
        failed = "; ".join(f"{v.label}: {v.detail} (limit: {v.threshold})" for v in result.vetoes)
        raise HTTPException(
            status_code=422,
            detail=f"vetoed by risk rules {rules.rule_version} (risk check {row.id}): {failed}",
        )
    return row.id, row.portfolio_snapshot_id


@router.post("/journal", status_code=201)
def create_entry(body: NewEntry, session: SessionDep, pinned: WriteTime) -> JournalCardOut:
    """A Thesis Card (version 1) and its decision, TRADE or NO TRADE, in one transaction."""
    who = subject(session, body.ticker)
    set_actor(session, ACTOR)
    when = _times(session, pinned)
    card = _card_row(session, who, body, uuid4(), 1, when)
    closes = closes_at(session, who, when.at, when.now)
    choice = body.decision
    if choice.decision == "trade" and closes.stock is None:
        raise HTTPException(
            status_code=422, detail=f"no end-of-day close of {who.ticker} known now"
        )
    checked = _risk_check(session, who, choice, when) if choice.decision == "trade" else None
    session.add(card)
    session.flush()
    session.add(
        _paper(
            thesis_card_id=card.id,
            risk_check_id=checked[0] if checked else None,
            portfolio_snapshot_id=checked[1] if checked else None,
            instrument_id=who.instrument.id,
            ticker=who.ticker,
            strategy_id=_strategy(session, card.signal_ids),
            signal_ids=card.signal_ids,
            decision=choice.decision,
            side=choice.side,
            quantity=choice.quantity,
            order_type=choice.order_type,
            limit_price=choice.limit_price,
            max_loss=choice.max_loss,
            no_trade_reason=choice.no_trade_reason,
            note=choice.note,
            exits_decision_id=None,
            entry_close=closes.model_dump(mode="json") if closes.stock else None,
            known_at=when.at,
            system_time=when.now,
        )
    )
    _commit(session, "the entry could not be saved; reload and try again")
    return journal_card(session, card.card_id, when.at, None)


@router.post("/journal/{card_id}/versions", status_code=201)
def add_version(
    card_id: UUID, body: CardContent, session: SessionDep, pinned: WriteTime
) -> JournalCardOut:
    """A new version of a card (the latest + 1); earlier versions and decisions stay."""
    latest = _versions(session, card_id, None)
    if not latest:
        raise HTTPException(status_code=404, detail=f"no thesis card {card_id}")
    who = subject(session, latest[-1].ticker)
    set_actor(session, ACTOR)
    when = _times(session, pinned)
    if when.at < latest[-1].known_at:
        raise HTTPException(status_code=409, detail="a version cannot precede the latest one")
    session.add(_card_row(session, who, body, card_id, latest[-1].version + 1, when))
    _commit(session, "another version was just saved; reload and try again")
    return journal_card(session, card_id, when.at, None)


@router.post("/journal/decisions/{decision_id}/exit", status_code=201)
def exit_trade(
    decision_id: UUID, body: ExitIn, session: SessionDep, pinned: WriteTime
) -> JournalCardOut:
    """Close an open paper TRADE at the last close known now: a new decision, opposite side."""
    entry = session.get(TradeDecision, decision_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no decision {decision_id}")
    exited = session.scalar(
        select(TradeDecision.id).where(TradeDecision.exits_decision_id == entry.id)
    )
    if entry.decision != "trade" or entry.exits_decision_id is not None or exited is not None:
        raise HTTPException(status_code=409, detail="only an open paper TRADE can be exited")
    card = session.get_one(ThesisCard, entry.thesis_card_id)
    who = subject(session, entry.ticker)
    set_actor(session, ACTOR)
    when = _times(session, pinned)
    if when.at < entry.known_at:
        raise HTTPException(status_code=409, detail="an exit cannot precede its entry")
    closes = closes_at(session, who, when.at, when.now)
    if closes.stock is None:
        raise HTTPException(
            status_code=422, detail=f"no end-of-day close of {who.ticker} known now"
        )
    session.add(
        _paper(
            thesis_card_id=_versions(session, card.card_id, None)[-1].id,
            instrument_id=entry.instrument_id,
            ticker=entry.ticker,
            strategy_id=entry.strategy_id,
            signal_ids=entry.signal_ids,
            decision="trade",
            side="sell" if entry.side == "buy" else "buy",
            quantity=entry.quantity,
            order_type="market",
            limit_price=None,
            max_loss=None,
            no_trade_reason=None,
            note=body.note,
            exits_decision_id=entry.id,
            entry_close=closes.model_dump(mode="json"),
            known_at=when.at,
            system_time=when.now,
        )
    )
    _commit(session, "this TRADE was just exited")
    return journal_card(session, card.card_id, when.at, None)


# ---------- reads ----------


def _versions(session: Session, card_id: UUID, at: datetime | None) -> list[ThesisCard]:
    query = select(ThesisCard).where(ThesisCard.card_id == card_id)
    if at is not None:
        query = query.where(ThesisCard.known_at <= at)
    return list(session.scalars(query.order_by(ThesisCard.version)))


def card_out(row: ThesisCard) -> CardOut:
    return CardOut(
        id=row.id,
        card_id=row.card_id,
        version=row.version,
        ticker=row.ticker,
        known_at=row.known_at,
        system_time=row.system_time,
        thesis=row.thesis,
        evidence=[EvidenceOut.model_validate(e) for e in row.evidence],
        catalysts=[Catalyst.model_validate(c) for c in row.catalysts],
        invalidation=row.invalidation,
        valuation=ValuationSnapshot.model_validate(row.valuation),
        signal_ids=row.signal_ids,
        notes=row.notes,
        author=row.author,
        created_at=row.created_at,
    )


def _mark(close: CloseOut | None) -> Mark | None:
    return Mark(close.day, close.close, close.published_at) if close else None


class Performance:
    """Paper performance of decisions at one viewing time; closes and splits read once each."""

    def __init__(self, session: Session, at: datetime) -> None:
        self.session = session
        self.at = at
        self.benchmark = instruments_by_symbol(session, [BENCHMARK]).get(BENCHMARK)
        self._closes: dict[str, CloseOut | None] = {}
        self._splits: dict[UUID, list[Split]] = {}

    def _close(self, instrument_id: UUID | None, symbol: str) -> CloseOut | None:
        if symbol not in self._closes:
            self._closes[symbol] = last_close(self.session, instrument_id, symbol, self.at, None)
        return self._closes[symbol]

    def of(self, row: TradeDecision, exit_row: TradeDecision | None) -> PerformanceOut:
        entry = Closes.model_validate(row.entry_close) if row.entry_close else None
        if exit_row is not None and exit_row.entry_close:
            out = Closes.model_validate(exit_row.entry_close)
            mark, benchmark_mark = out.stock, out.benchmark
        else:
            mark = self._close(row.instrument_id, row.ticker)
            benchmark_mark = self._close(self.benchmark, BENCHMARK)
        if row.instrument_id not in self._splits:
            self._splits[row.instrument_id] = _splits(self.session, row.instrument_id, self.at)
        result = paper_return(
            row.side if row.decision == "trade" else None,  # type: ignore[arg-type]
            row.quantity,
            _mark(entry.stock if entry else None),
            _mark(mark),
            self._splits[row.instrument_id],
            _mark(entry.benchmark if entry else None),
            _mark(benchmark_mark),
            row.max_loss,
        )
        return PerformanceOut(
            status=result.status,
            detail=result.detail,
            open=row.decision == "trade" and exit_row is None,
            entry=entry.stock if entry else None,
            mark=mark,
            split_factor=result.split_factor,
            entry_basis=result.entry_basis,
            return_pct=result.return_pct,
            pnl=result.pnl,
            benchmark=BENCHMARK,
            benchmark_return_pct=result.benchmark_return_pct,
            relative=result.relative,
            max_loss_breached=result.max_loss_breached,
        )


def decisions_out(
    session: Session, rows: Iterable[TradeDecision], at: datetime
) -> list[JournalDecisionOut]:
    rows = list(rows)
    versions = dict(
        session.execute(
            select(ThesisCard.id, ThesisCard.version).where(
                ThesisCard.id.in_({r.thesis_card_id for r in rows})
            )
        ).all()
    )
    exits = {r.exits_decision_id: r for r in rows if r.exits_decision_id is not None}
    performance = Performance(session, at)
    return [
        JournalDecisionOut(
            id=r.id,
            thesis_card_id=r.thesis_card_id,
            card_version=versions[r.thesis_card_id],
            decision=r.decision,  # type: ignore[arg-type]
            side=r.side,  # type: ignore[arg-type]
            quantity=r.quantity,
            order_type=r.order_type,
            limit_price=r.limit_price,
            max_loss=r.max_loss,
            no_trade_reason=r.no_trade_reason,  # type: ignore[arg-type]
            note=r.note,
            exits_decision_id=r.exits_decision_id,
            exited_by=exits[r.id].id if r.id in exits else None,
            closes=Closes.model_validate(r.entry_close) if r.entry_close else None,
            strategy_id=r.strategy_id,
            signal_ids=r.signal_ids,
            mode="paper",
            approval_state=r.approval_state,
            known_at=r.known_at,
            system_time=r.system_time,
            performance=None
            if r.exits_decision_id is not None
            else performance.of(r, exits.get(r.id)),
        )
        for r in rows
    ]


def _decisions(
    session: Session, at: datetime, card_ids: Iterable[UUID] | None = None
) -> list[TradeDecision]:
    query = select(TradeDecision).where(TradeDecision.known_at <= at)
    if card_ids is not None:
        query = query.where(
            TradeDecision.thesis_card_id.in_(
                select(ThesisCard.id).where(ThesisCard.card_id.in_(list(card_ids)))
            )
        )
    return list(session.scalars(query.order_by(TradeDecision.known_at, TradeDecision.created_at)))


def journal_card(
    session: Session, card_id: UUID, at: datetime, version: int | None
) -> JournalCardOut:
    versions = _versions(session, card_id, at)
    if not versions:
        raise HTTPException(status_code=404, detail=f"no thesis card {card_id} known then")
    shown = (
        versions[-1]
        if version is None
        else next((v for v in versions if v.version == version), None)
    )
    if shown is None:
        raise HTTPException(status_code=404, detail=f"no version {version} known then")
    return JournalCardOut(
        known_at=at,
        card=card_out(shown),
        versions=[VersionOut(id=v.id, version=v.version, known_at=v.known_at) for v in versions],
        decisions=decisions_out(session, _decisions(session, at, [card_id]), at),
    )


@router.get("/journal")
def journal(session: SessionDep, known_at: KnownAt = None, ticker: str | None = None) -> JournalOut:
    """Every card known at T, newest first, with its first decision, exit and performance."""
    at = known_at_or_now(session, known_at)
    query = select(ThesisCard).where(ThesisCard.known_at <= at)
    if ticker:
        query = query.where(ThesisCard.ticker == ticker.upper())
    cards: dict[UUID, list[ThesisCard]] = {}
    for row in session.scalars(query.order_by(ThesisCard.version)):
        cards.setdefault(row.card_id, []).append(row)
    decisions = decisions_out(session, _decisions(session, at, cards), at)
    card_of = {v.id: card_id for card_id, versions in cards.items() for v in versions}
    entries = []
    for card_id, versions in cards.items():
        mine = [d for d in decisions if card_of.get(d.thesis_card_id) == card_id]
        first = next((d for d in mine if d.exits_decision_id is None), None)
        entries.append(
            JournalRow(
                card_id=card_id,
                ticker=versions[-1].ticker,
                version=versions[-1].version,
                thesis=versions[-1].thesis,
                known_at=versions[0].known_at,
                signal_ids=versions[-1].signal_ids,
                decision=first,
                exit=next((d for d in mine if first and d.exits_decision_id == first.id), None),
            )
        )
    entries.sort(key=lambda e: e.known_at, reverse=True)
    return JournalOut(known_at=at, entries=entries)


@router.get("/journal/{card_id}")
def journal_entry(
    card_id: UUID,
    session: SessionDep,
    known_at: KnownAt = None,
    version: int | None = Query(default=None, ge=1),
) -> JournalCardOut:
    return journal_card(session, card_id, known_at_or_now(session, known_at), version)


def _item(
    kind: str, label: str, stored: dict[str, Any], again: dict[str, Any] | None
) -> ReplayItem:
    result = compare(stored, again)
    return ReplayItem(
        kind=kind,
        label=label,
        status=result.status,
        changed=result.changed,
        stored=stored,
        again=again,
    )


@router.get("/journal/{card_id}/replay")
def replay(
    card_id: UUID, session: SessionDep, version: int | None = Query(default=None, ge=1)
) -> ReplayOut:
    """Read the card's evidence, valuation and its decisions' closes again at the stored
    (T, S) and compare each with what was stored (acceptance 1)."""
    versions = _versions(session, card_id, None)
    card = (
        versions[-1]
        if version is None
        else next((v for v in versions if v.version == version), None)
    )
    if card is None:
        raise HTTPException(status_code=404, detail=f"no thesis card {card_id} version {version}")
    who = subject(session, card.ticker)
    at, system_time = card.known_at, card.system_time
    evidence = []
    for stored in card.evidence:
        again = resolve(session, who, stored["kind"], stored["ref"], at, system_time)
        evidence.append(
            _item(
                stored["kind"],
                stored["label"],
                stored["snapshot"],
                again.snapshot if again else None,
            )
        )
    valuation = _item(
        "valuation",
        "Base DCF against the price",
        card.valuation,
        valuation_at(session, who, at, system_time).model_dump(mode="json"),
    )
    decisions = [
        _item(
            "decision_closes",
            f"{row.decision.replace('_', ' ').upper()} closes at {row.known_at:%Y-%m-%d %H:%M} UTC",
            row.entry_close or {},
            closes_at(session, who, row.known_at, row.system_time).model_dump(mode="json")
            if row.entry_close
            else {},
        )
        for row in session.scalars(
            select(TradeDecision)
            .where(TradeDecision.thesis_card_id == card.id)
            .order_by(TradeDecision.known_at)
        )
    ]
    items = [*evidence, valuation, *decisions]
    return ReplayOut(
        card_id=card_id,
        version=card.version,
        known_at=at,
        system_time=system_time,
        identical=all(i.status == "identical" for i in items),
        evidence=evidence,
        valuation=valuation,
        decisions=decisions,
    )


@router.get("/instruments/{ticker}/evidence")
def evidence_candidates(
    ticker: str, session: SessionDep, known_at: KnownAt = None
) -> CandidatesOut:
    who = subject(session, ticker)
    at = known_at_or_now(session, known_at)
    return CandidatesOut(ticker=who.ticker, known_at=at, candidates=candidates(session, who, at))
