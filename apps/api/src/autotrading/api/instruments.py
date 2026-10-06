"""Instrument API (M0.5b, M1.1): universe equities and their SEC fundamentals as known at a time.

Facts come from `as_of(known_at)` (ADR-012) for the current issuer and its predecessors
(ADR-014); the current issuer's value wins for a period both reported. Per-share values and
share counts carry their split-adjusted value on the basis of known_at beside the reported one
(domain/splits.py, ADR-021), using the splits effective by then. Read-only.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.db.models import (
    Entity,
    EntityRelationship,
    Filing,
    FinancialFact,
    Identifier,
    IngestionRun,
    Instrument,
    SplitEvent,
)
from autotrading.domain.derived import DERIVED_ANNUAL, DERIVED_BALANCE, Derived, derive_all
from autotrading.domain.fundamentals import (
    ANNUAL_METRICS,
    BALANCE_SHEET_METRICS,
    LATEST_METRICS,
    Period,
    Succession,
    annual_periods,
    balance_sheet_periods,
    entity_precedence,
    issuer_at,
    merge_by_precedence,
)
from autotrading.domain.quarters import Quarter, quarters, trailing_twelve_months
from autotrading.domain.splits import ADJUSTED_METRICS, Split, adjust
from autotrading.repositories.facts import as_of_query

router = APIRouter(tags=["instruments"])

SEC_SOURCE = "sec_edgar"
SEC_NAMESPACE = "sec"
PERIODIC_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A")
PER_SHARE_HISTORY_METRICS = ("eps_diluted", "diluted_shares")
PER_SHARE_HISTORY_YEARS = 15
QUARTERLY_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "depreciation_amortization",
    "share_repurchases",
    "shares_repurchased",
    "dividends_paid",
    "stock_based_compensation",
)
QUARTER_COLUMNS = 8


class EntityOut(BaseModel):
    id: UUID
    name: str
    cik: str | None
    role: Literal["issuer", "predecessor"]
    # For a predecessor: when the successor took over, and the filing that shows it.
    succeeded_at: datetime | None = None
    evidence_url: str | None = None
    evidence_accession: str | None = None


class FilingRef(BaseModel):
    accession: str
    form: str | None
    url: str
    published_at: datetime
    published_at_precision: str


class PreviousVersion(BaseModel):
    value: Decimal
    filing: FilingRef


class SplitOut(BaseModel):
    ex_date: date
    old_rate: Decimal
    new_rate: Decimal
    kind: str
    source_id: str
    source_url: str


class SplitAdjusted(BaseModel):
    """The value on the basis of known_at: share counts times `factor`, per-share amounts
    divided by it, for the splits after the value's filing (ADR-021)."""

    value: Decimal
    factor: str  # e.g. "4", "28", "3/2"
    splits: list[date]  # ex-dates applied


class FactCell(BaseModel):
    kind: Literal["reported"] = "reported"
    value: Decimal
    unit: str
    currency: str | None
    period_start: date | None
    period_end: date
    fiscal_period: str | None
    source_concept: str | None
    filing: FilingRef
    restated: bool
    previous: PreviousVersion | None
    reported_by: UUID
    split_adjusted: SplitAdjusted | None = None  # None: no split after the filing


class DerivedInput(BaseModel):
    """One input of a derived value: a reported fact, a derived quarter, or 0 assumed."""

    metric_id: str
    value: Decimal | None  # None: not reported, counted as 0 (assumed_zero)
    period_start: date | None
    period_end: date
    filing: FilingRef | None  # the filing of a reported input
    assumed_zero: bool = False


class DerivedCell(BaseModel):
    """A value computed at read time from inputs known at known_at (ADR-021)."""

    kind: Literal["derived"] = "derived"
    value: Decimal
    unit: str
    currency: str | None
    period_start: date | None
    period_end: date
    method: str  # e.g. "operating_cash_flow - capex", "ytd_difference", "quarter_sum"
    inputs: list[DerivedInput]
    split_adjusted: SplitAdjusted | None = None


Cell = Annotated[FactCell | DerivedCell, Field(discriminator="kind")]


class PeriodColumn(BaseModel):
    period_start: date | None
    period_end: date


class MetricRow(BaseModel):
    metric_id: str
    cells: list[Cell | None]  # one per period column; None = not reported or not derivable


class FactTable(BaseModel):
    periods: list[PeriodColumn]
    rows: list[MetricRow]


class QuarterRow(BaseModel):
    metric_id: str
    cells: list[DerivedCell | None]  # one per quarter column
    ttm: DerivedCell | None  # trailing twelve months at the latest column; flows only


class QuarterTable(BaseModel):
    periods: list[PeriodColumn]  # oldest first
    rows: list[QuarterRow]


class InstrumentSummary(BaseModel):
    ticker: str
    name: str
    cik: str | None
    exchange: str | None
    predecessors: list[str]
    latest_report: FilingRef | None


class InstrumentList(BaseModel):
    instruments: list[InstrumentSummary]
    last_refresh_at: datetime | None


class Fundamentals(BaseModel):
    ticker: str
    exchange: str | None
    known_at: datetime
    issuer: EntityOut  # the issuer at known_at
    entities: list[EntityOut]  # current issuer first, then predecessors
    annual: FactTable
    balance_sheet: FactTable
    # Last 8 quarters from year-to-date values, with trailing twelve months (M1.1).
    quarterly: QuarterTable
    # Diluted EPS and shares for up to 15 fiscal years, reported and split-adjusted (M1.1).
    per_share_history: FactTable
    latest: list[MetricRow]  # one cell each, with its own date: cover-page shares, authorization
    splits: list[SplitOut]  # effective by known_at, oldest first
    last_refresh_at: datetime | None


# ---------- endpoints ----------


@router.get("/instruments")
def list_instruments(session: SessionDep) -> InstrumentList:
    rows = session.execute(
        select(Identifier.id_value, Instrument, Entity)
        .join(Instrument, Instrument.id == Identifier.instrument_id)
        .join(Entity, Entity.id == Instrument.entity_id)
        .where(open_sec("ticker"))
        .order_by(Identifier.id_value)
    ).all()
    summaries = []
    for ticker, instrument, entity in rows:
        chain = issuer_chain(session, entity.id)
        summaries.append(
            InstrumentSummary(
                ticker=ticker,
                name=entity.name,
                cik=_cik(session, entity.id),
                exchange=instrument.primary_exchange,
                predecessors=[session.get_one(Entity, e).name for e in chain.order[1:]],
                latest_report=_latest_report(session, chain.order),
            )
        )
    return InstrumentList(instruments=summaries, last_refresh_at=_last_refresh(session))


@router.get("/instruments/{ticker}/fundamentals")
def fundamentals(
    ticker: str,
    session: SessionDep,
    known_at: Annotated[
        AwareDatetime | None, Query(description="Point in time (ADR-012); default now")
    ] = None,
) -> Fundamentals:
    found = session.execute(
        select(Instrument, Entity)
        .join(Identifier, Identifier.instrument_id == Instrument.id)
        .join(Entity, Entity.id == Instrument.entity_id)
        .where(open_sec("ticker"), Identifier.id_value == ticker.upper())
    ).first()
    if found is None:
        raise HTTPException(status_code=404, detail=f"unknown instrument {ticker!r}")
    instrument, current = found
    at: datetime = known_at or session.execute(select(func.now())).scalar_one()
    chain = issuer_chain(session, current.id)

    facts = session.scalars(
        as_of_query(FinancialFact, known_at=at).where(
            FinancialFact.entity_id.in_(chain.order),
            FinancialFact.metric_id.in_(ANNUAL_METRICS + BALANCE_SHEET_METRICS + LATEST_METRICS),
        )
    ).all()
    merged = merge_by_precedence(facts, chain.order)
    years = annual_periods(merged)
    balance_dates = balance_sheet_periods(merged, years)
    split_rows = session.scalars(
        select(SplitEvent)
        .where(SplitEvent.instrument_id == instrument.id, SplitEvent.published_at <= at)
        .order_by(SplitEvent.ex_date)
    ).all()
    splits = [Split(s.ex_date, s.old_rate, s.new_rate) for s in split_rows]
    cells = _CellBuilder(session, merged, splits, at)

    entities = [_entity_out(session, e, chain) for e in chain.order]
    issuer_id = issuer_at(current.id, chain.successions, at)
    return Fundamentals(
        ticker=ticker.upper(),
        exchange=instrument.primary_exchange,
        known_at=at,
        issuer=next(e for e in entities if e.id == issuer_id),
        entities=entities,
        annual=cells.table(ANNUAL_METRICS + DERIVED_ANNUAL, years),
        balance_sheet=cells.table(BALANCE_SHEET_METRICS + DERIVED_BALANCE, balance_dates),
        quarterly=cells.quarter_table(QUARTERLY_METRICS),
        latest=cells.latest(LATEST_METRICS),
        per_share_history=cells.table(
            PER_SHARE_HISTORY_METRICS, annual_periods(merged, count=PER_SHARE_HISTORY_YEARS)
        ),
        splits=[
            SplitOut(
                ex_date=s.ex_date,
                old_rate=s.old_rate,
                new_rate=s.new_rate,
                kind=s.kind,
                source_id=s.source_id,
                source_url=s.source_url,
            )
            for s in split_rows
        ],
        last_refresh_at=_last_refresh(session),
    )


# ---------- helpers ----------


@dataclass(frozen=True)
class IssuerChain:
    """The current issuer and its predecessors (ADR-014), nearest first."""

    order: list[UUID]
    successions: list[Succession]
    links: dict[UUID, EntityRelationship]  # by predecessor entity


def issuer_chain(session: Session, current: UUID) -> IssuerChain:
    links = session.scalars(
        select(EntityRelationship).where(EntityRelationship.relationship_type == "successor_issuer")
    ).all()
    successions = [
        Succession(link.predecessor_entity_id, link.successor_entity_id, link.effective_at)
        for link in links
    ]
    order = entity_precedence(current, successions)
    return IssuerChain(
        order=order,
        successions=[s for s in successions if s.successor_entity_id in order],
        links={link.predecessor_entity_id: link for link in links},
    )


def open_sec(id_type: str) -> ColumnElement[bool]:
    """Open-ended SEC identifiers of one type (ticker or CIK)."""
    return and_(
        Identifier.id_type == id_type,
        Identifier.id_namespace == SEC_NAMESPACE,
        Identifier.valid_to.is_(None),
    )


def _cik(session: Session, entity_id: UUID) -> str | None:
    return session.scalar(
        select(Identifier.id_value).where(open_sec("cik"), Identifier.entity_id == entity_id)
    )


def _entity_out(session: Session, entity_id: UUID, chain: IssuerChain) -> EntityOut:
    entity = session.get_one(Entity, entity_id)
    if entity_id == chain.order[0]:
        return EntityOut(
            id=entity.id, name=entity.name, cik=_cik(session, entity.id), role="issuer"
        )
    link = chain.links[entity_id]
    return EntityOut(
        id=entity.id,
        name=entity.name,
        cik=_cik(session, entity.id),
        role="predecessor",
        succeeded_at=link.effective_at,
        evidence_url=link.evidence_url,
        evidence_accession=link.evidence_accession,
    )


def _last_refresh(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(IngestionRun.finished_at)).where(
            IngestionRun.source_id == SEC_SOURCE, IngestionRun.status == "succeeded"
        )
    )


def _latest_report(session: Session, entity_ids: list[UUID]) -> FilingRef | None:
    for entity_id in entity_ids:  # the current issuer first
        filing = session.scalars(
            select(Filing)
            .where(Filing.entity_id == entity_id, Filing.form.in_(PERIODIC_FORMS))
            .order_by(Filing.published_at.desc())
            .limit(1)
        ).first()
        if filing is not None:
            return FilingRef(
                accession=filing.accession_number,
                form=filing.form,
                url=filing.source_url,
                published_at=filing.published_at,
                published_at_precision=filing.published_at_precision,
            )
    return None


@dataclass(frozen=True)
class FactView:
    """A stored fact as the pure domain functions see it (domain/derived.ValueFact)."""

    row: FinancialFact

    @property
    def metric_id(self) -> str:
        return self.row.metric_id

    @property
    def value(self) -> Decimal:
        return self.row.value

    @property
    def period_start(self) -> date | None:
        return self.row.period_start

    @property
    def period_end(self) -> date:
        return self.row.period_end

    @property
    def reported_at(self) -> datetime:
        return self.row.published_at


class _CellBuilder:
    """Builds table cells; filing forms and earlier versions are loaded once per request."""

    def __init__(
        self, session: Session, facts: list[FinancialFact], splits: list[Split], at: datetime
    ) -> None:
        self._facts = facts
        self._splits = splits
        self._at = at
        self._views = [FactView(f) for f in facts]
        self._derived = {
            (d.metric_id, d.period_start, d.period_end): d for d in derive_all(self._views)
        }
        superseded_ids = [f.supersedes_fact_id for f in facts if f.supersedes_fact_id]
        self._previous = {
            row.id: row
            for row in session.scalars(
                select(FinancialFact).where(FinancialFact.id.in_(superseded_ids))
            )
        }
        accessions = {f.accession_id for f in facts} | {
            p.accession_id for p in self._previous.values()
        }
        self._forms = dict(
            session.execute(
                select(Filing.accession_number, Filing.form)
                .where(Filing.accession_number.in_([a for a in accessions if a]))
                .ext(distinct_on(Filing.accession_number))
                .order_by(Filing.accession_number)
            ).all()
        )

    def table(self, metrics: tuple[str, ...], periods: list[Period]) -> FactTable:
        by_key = {(f.metric_id, f.period_start, f.period_end): f for f in self._facts}

        def cell(metric: str, p: Period) -> FactCell | DerivedCell | None:
            derived = self._derived.get((metric, p.start, p.end))
            if derived is not None:
                return self._derived_cell(derived)
            return self._cell(by_key.get((metric, p.start, p.end)))

        return FactTable(
            periods=[PeriodColumn(period_start=p.start, period_end=p.end) for p in periods],
            rows=[MetricRow(metric_id=m, cells=[cell(m, p) for p in periods]) for m in metrics],
        )

    def latest(self, metrics: tuple[str, ...]) -> list[MetricRow]:
        out = []
        for metric in metrics:
            facts = [f for f in self._facts if f.metric_id == metric]
            if facts and (cell := self._cell(max(facts, key=lambda f: f.period_end))):
                out.append(MetricRow(metric_id=metric, cells=[cell]))
        return out

    def quarter_table(self, metrics: tuple[str, ...]) -> QuarterTable:
        series = {m: quarters(self._views, m) for m in metrics if m != "free_cash_flow"}
        series["free_cash_flow"] = _fcf_quarters(series["operating_cash_flow"], series["capex"])
        ends = sorted({(q.period_start, q.period_end) for qs in series.values() for q in qs})
        columns = ends[-QUARTER_COLUMNS:]
        rows = []
        for metric in metrics:
            by_period = {(q.period_start, q.period_end): q for q in series[metric]}
            ttm = trailing_twelve_months(series[metric])
            rows.append(
                QuarterRow(
                    metric_id=metric,
                    cells=[
                        self._quarter_cell(q) if (q := by_period.get(c)) else None for c in columns
                    ],
                    ttm=self._ttm_cell(metric, *ttm)
                    if ttm and ttm[1][-1].period_end == columns[-1][1]
                    else None,
                )
            )
        return QuarterTable(
            periods=[PeriodColumn(period_start=s, period_end=e) for s, e in columns], rows=rows
        )

    def _unit(self, metric: str) -> tuple[str, str | None]:
        sample = next((f for f in self._facts if f.metric_id == metric), None)
        if sample is not None:
            return sample.unit, sample.currency
        return ("USD/shares", "USD") if metric == "eps_diluted" else ("USD", "USD")

    def _input(self, metric: str, view: FactView) -> DerivedInput:
        fact = view.row
        return DerivedInput(
            metric_id=metric,
            value=fact.value,
            period_start=fact.period_start,
            period_end=fact.period_end,
            filing=self._filing(fact),
        )

    def _derived_cell(self, derived: Derived[FactView]) -> DerivedCell:
        unit, currency = self._unit("cash")
        inputs = [
            self._input(metric, fact)
            if fact is not None
            else DerivedInput(
                metric_id=metric,
                value=None,
                period_start=None,
                period_end=derived.period_end,
                filing=None,
                assumed_zero=True,
            )
            for metric, fact in derived.inputs
        ]
        return DerivedCell(
            value=derived.value,
            unit=unit,
            currency=currency,
            period_start=derived.period_start,
            period_end=derived.period_end,
            method=derived.method,
            inputs=inputs,
        )

    def _quarter_cell(self, quarter: Quarter[FactView]) -> DerivedCell:
        unit, currency = self._unit(quarter.metric_id)
        adjusted = None
        if quarter.method == "reported" and quarter.metric_id in ADJUSTED_METRICS:
            (view,) = quarter.inputs
            adjusted = self._adjusted(view.row)
        return DerivedCell(
            value=quarter.value,
            unit=unit,
            currency=currency,
            period_start=quarter.period_start,
            period_end=quarter.period_end,
            method=quarter.method,
            inputs=[self._input(quarter.metric_id, f) for f in quarter.inputs],
            split_adjusted=adjusted,
        )

    def _ttm_cell(self, metric: str, total: Decimal, last: list[Quarter[FactView]]) -> DerivedCell:
        unit, currency = self._unit(metric)
        return DerivedCell(
            value=total,
            unit=unit,
            currency=currency,
            period_start=last[0].period_start,
            period_end=last[-1].period_end,
            method="quarter_sum",
            inputs=[
                DerivedInput(
                    metric_id=metric,
                    value=q.value,
                    period_start=q.period_start,
                    period_end=q.period_end,
                    filing=None,
                )
                for q in last
            ],
        )

    def _filing(self, fact: FinancialFact) -> FilingRef:
        accession = fact.accession_id or ""
        return FilingRef(
            accession=accession,
            form=self._forms.get(accession),
            url=fact.source_url,
            published_at=fact.published_at,
            published_at_precision=fact.published_at_precision,
        )

    def _cell(self, fact: FinancialFact | None) -> FactCell | None:
        if fact is None:
            return None
        previous = self._previous.get(fact.supersedes_fact_id) if fact.supersedes_fact_id else None
        return FactCell(
            value=fact.value,
            unit=fact.unit,
            currency=fact.currency,
            period_start=fact.period_start,
            period_end=fact.period_end,
            fiscal_period=fact.fiscal_period,
            source_concept=fact.source_concept,
            filing=self._filing(fact),
            restated=fact.restated_flag,
            previous=(
                PreviousVersion(value=previous.value, filing=self._filing(previous))
                if previous is not None
                else None
            ),
            reported_by=fact.entity_id,
            split_adjusted=self._adjusted(fact),
        )

    def _adjusted(self, fact: FinancialFact) -> SplitAdjusted | None:
        if fact.metric_id not in ADJUSTED_METRICS:
            return None
        adjusted = adjust(fact.metric_id, fact.value, fact.published_at, self._at, self._splits)
        if adjusted is None:
            return None
        return SplitAdjusted(
            value=adjusted.value,
            factor=str(adjusted.factor),
            splits=[s.ex_date for s in adjusted.splits],
        )


def _fcf_quarters(
    ocf: list[Quarter[FactView]], capex: list[Quarter[FactView]]
) -> list[Quarter[FactView]]:
    """Free cash flow per quarter: both quarters known, their inputs kept (ADR-021)."""
    by_period = {(q.period_start, q.period_end): q for q in capex}
    out = []
    for q in ocf:
        c = by_period.get((q.period_start, q.period_end))
        if c is not None:
            out.append(
                Quarter(
                    "free_cash_flow",
                    q.number,
                    q.fiscal_year_end,
                    q.period_start,
                    q.period_end,
                    q.value - c.value,
                    "operating_cash_flow - capex",
                    (*q.inputs, *c.inputs),
                )
            )
    return out
