"""Overview API (M0.6 overview, ADR-016): the macro dashboard as known at a time.

Six blocks (inflation, labor, growth, policy, curve, risk). Each block carries its latest
values, computed indicators (domain/indicators.py), chart points and one rule-based insight
sentence that lists the observations and vintages it used. Everything is computed from
`as_of(known_at)` (ADR-012), so a past date gives the dashboard as it could be computed then.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from autotrading.api.data_health import SessionDep
from autotrading.api.prices import (
    MarketState,
    market_state,
    price_history,
    provider_ready,
    quote_out,
)
from autotrading.db.models import IngestionRun, MacroObservation, MacroSeries
from autotrading.domain import indicators as ind
from autotrading.domain.indicators import Point
from autotrading.domain.market_calendar import NEW_YORK
from autotrading.domain.prices import FeedStatus, change_percent
from autotrading.domain.provenance import end_of_day
from autotrading.ingestion.schedule import market_calendar
from autotrading.repositories.facts import as_of_query
from autotrading.repositories.prices import instruments_by_symbol, latest_quotes

router = APIRouter(tags=["overview"])

Unit = Literal["percent", "pp", "thousands", "observations", "percentile", "index", "usd"]
# How far back each frequency is read: enough for 36 months, the Sahm rule, 12 quarters and
# one year of daily data.
LOOKBACK = {"M": timedelta(days=4 * 366), "Q": timedelta(days=5 * 366), "D": timedelta(days=380)}
CHART_POINTS = {"M": 36, "Q": 12}


class InputRef(BaseModel):
    series_id: str
    observation_date: date
    vintage: date


class ChartPoint(BaseModel):
    day: date
    value: Decimal


class Chart(BaseModel):
    term_id: str  # glossary term of the plotted values
    unit: Unit
    zero_line: bool
    points: list[ChartPoint]


class LatestValue(BaseModel):
    series_id: str
    term_id: str
    title: str | None
    units_short: str | None
    observation_date: date
    value: Decimal
    vintage: date


class Indicator(BaseModel):
    term_id: str
    value: Decimal
    unit: Unit
    as_of: date  # the observation date the value refers to
    label: str | None = None  # rule-based label, e.g. "above" target, "inverted", "low"
    since: date | None = None


class Insight(BaseModel):
    text: str
    inputs: list[InputRef]


class PriceTile(BaseModel):
    """One market price on the overview, with the feed status shown next to it (errata E4)."""

    symbol: str
    feed_status: FeedStatus
    last: Decimal | None = None
    change_pct: Decimal | None = None
    published_at: datetime | None = None


class Block(BaseModel):
    id: Literal["markets", "inflation", "labor", "growth", "policy", "curve", "risk"]
    title: str
    latest: list[LatestValue]
    indicators: list[Indicator]
    charts: list[Chart]
    insight: Insight | None
    prices: list[PriceTile] = []


class Overview(BaseModel):
    known_at: datetime
    blocks: list[Block]
    last_refresh_at: datetime | None
    market: MarketState | None = None  # live view only: is the US session open now


# ---------- data access ----------


@dataclass(frozen=True)
class Obs:
    day: date
    value: Decimal
    vintage: date


class _Data:
    """As-of observations per series, loaded once per request."""

    def __init__(self, session: Session, known_at: datetime, *, live: bool = False) -> None:
        self.session = session
        self.known_at = known_at
        self.live = live  # no known_at given: quotes instead of daily closes
        self.series = {s.id: s for s in session.scalars(select(MacroSeries))}
        self._cache: dict[str, list[Obs]] = {}

    def obs(self, series_id: str, *, full_history: bool = False) -> list[Obs]:
        """As-of observations, oldest first: the frequency's lookback, or all of them (for
        streaks and percentiles that must not be cut short by the window)."""
        key = f"{series_id}:{full_history}"
        if key not in self._cache:
            series = self.series.get(series_id)
            frequency = (series.frequency_short if series else None) or "D"
            known = as_of_query(MacroObservation, known_at=self.known_at).where(
                MacroObservation.series_id == series_id
            )
            if not full_history:
                cutoff = self.known_at.date() - LOOKBACK.get(frequency, LOOKBACK["D"])
                known = known.where(MacroObservation.observation_date >= cutoff)
            row = aliased(MacroObservation, known.subquery())
            self._cache[key] = [
                Obs(r.observation_date, r.value, r.vintage)
                for r in self.session.scalars(select(row).order_by(row.observation_date))
            ]
        return self._cache[key]

    def points(self, series_id: str, *, full_history: bool = False) -> list[Point]:
        return [Point(o.day, o.value) for o in self.obs(series_id, full_history=full_history)]

    def latest(self, series_id: str) -> LatestValue | None:
        rows = self.obs(series_id)
        series = self.series.get(series_id)
        if not rows or series is None:
            return None
        last = rows[-1]
        return LatestValue(
            series_id=series_id,
            term_id=series.term_id,
            title=series.title,
            units_short=series.units_short,
            observation_date=last.day,
            value=last.value,
            vintage=last.vintage,
        )

    def ref(self, series_id: str, back: int = 0) -> InputRef | None:
        rows = self.obs(series_id)
        if len(rows) <= back:
            return None
        o = rows[-1 - back]
        return InputRef(series_id=series_id, observation_date=o.day, vintage=o.vintage)

    def ref_on(self, series_id: str, day: date) -> InputRef | None:
        o = next((o for o in self.obs(series_id) if o.day == day), None)
        return InputRef(series_id=series_id, observation_date=day, vintage=o.vintage) if o else None

    def first_release(self, series_id: str, day: date) -> Obs | None:
        row = self.session.scalars(
            select(MacroObservation)
            .where(
                MacroObservation.series_id == series_id,
                MacroObservation.observation_date == day,
                MacroObservation.published_at <= self.known_at,
                MacroObservation.superseded_at.is_(None),
            )
            .ext(distinct_on(MacroObservation.observation_date))
            .order_by(MacroObservation.observation_date, MacroObservation.published_at)
        ).first()
        return Obs(row.observation_date, row.value, row.vintage) if row else None

    def chart(self, series_id: str, unit: Unit, *, zero_line: bool = False) -> Chart | None:
        series = self.series.get(series_id)
        points = self.points(series_id)
        if series is None or not points:
            return None
        limit = CHART_POINTS.get(series.frequency_short or "D")
        if limit:
            points = points[-limit:]
        else:  # daily: the last year
            points = [p for p in points if p.day > points[-1].day - timedelta(days=365)]
        return _chart(series.term_id, unit, points, zero_line)


def _chart(term_id: str, unit: Unit, points: list[Point], zero_line: bool = False) -> Chart:
    return Chart(
        term_id=term_id,
        unit=unit,
        zero_line=zero_line,
        points=[ChartPoint(day=p.day, value=p.value) for p in points],
    )


def _refs(*refs: InputRef | None) -> list[InputRef]:
    return [r for r in refs if r is not None]


def _fmt(value: Decimal, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def _signed(value: Decimal, digits: int = 0, suffix: str = "") -> str:
    return f"{value:+.{digits}f}{suffix}".replace("+-", "-")


def _month(day: date) -> str:
    return day.strftime("%b %Y")


# ---------- blocks ----------


def _inflation(data: _Data) -> Block:
    cpi, pce = data.points("CPIAUCSL"), data.points("PCEPILFE")
    cpi_yoy, pce_yoy = ind.yoy_percent(cpi), ind.yoy_percent(pce)
    indicators = []
    if cpi_yoy is not None:
        indicators.append(
            Indicator(
                term_id="cpi_inflation_yoy",
                value=cpi_yoy,
                unit="percent",
                as_of=cpi[-1].day,
                label=ind.relation_to_target(cpi_yoy),
            )
        )
    if pce_yoy is not None:
        indicators.append(
            Indicator(
                term_id="core_pce_inflation_yoy",
                value=pce_yoy,
                unit="percent",
                as_of=pce[-1].day,
                label=ind.relation_to_target(pce_yoy),
            )
        )
    insight = None
    if cpi_yoy is not None and pce_yoy is not None:
        relation = ind.relation_to_target(pce_yoy)
        insight = Insight(
            text=(
                f"CPI inflation is {_fmt(cpi_yoy)}% over 12 months ({_month(cpi[-1].day)}); "
                f"core PCE is {_fmt(pce_yoy)}% ({_month(pce[-1].day)}), "
                f"{relation} the Fed's 2% target."
            ),
            inputs=_refs(data.ref("CPIAUCSL"), data.ref("PCEPILFE")),
        )
    charts = []
    if yoy := ind.yoy_series(cpi)[-36:]:
        charts.append(_chart("cpi_inflation_yoy", "percent", yoy))
    return Block(
        id="inflation",
        title="Inflation",
        latest=[v for v in (data.latest("CPIAUCSL"), data.latest("PCEPILFE")) if v],
        indicators=indicators,
        charts=charts,
        insight=insight,
    )


def _labor(data: _Data) -> Block:
    payrolls, unrate = data.points("PAYEMS"), data.points("UNRATE")
    indicators: list[Indicator] = []
    parts: list[str] = []
    inputs = _refs(data.ref("PAYEMS"), data.ref("UNRATE"))
    change = ind.latest_change(payrolls)
    if change is not None:
        indicators.append(
            Indicator(
                term_id="payrolls_monthly_change",
                value=change,
                unit="thousands",
                as_of=payrolls[-1].day,
            )
        )
        parts.append(f"Payrolls {_signed(change, 0, 'K')} in {_month(payrolls[-1].day)}")
    if len(payrolls) >= 2:
        prior = data.obs("PAYEMS")[-2]
        first = data.first_release("PAYEMS", prior.day)
        if first is not None:
            moved = ind.revision(prior.value, first.value)
            indicators.append(
                Indicator(
                    term_id="payrolls_prior_month_revision",
                    value=moved,
                    unit="thousands",
                    as_of=prior.day,
                )
            )
            parts.append(
                f"{_month(prior.day)} revised {_signed(moved, 0, 'K')} from its first release"
                if moved
                else f"{_month(prior.day)} unrevised since its first release"
            )
            inputs.append(
                InputRef(series_id="PAYEMS", observation_date=first.day, vintage=first.vintage)
            )
    sahm = ind.sahm_indicator(unrate)
    if sahm is not None:
        triggered = sahm >= ind.SAHM_TRIGGER
        indicators.append(
            Indicator(
                term_id="sahm_rule_indicator",
                value=sahm,
                unit="pp",
                as_of=unrate[-1].day,
                label="triggered" if triggered else "not triggered",
            )
        )
        parts.append(
            f"unemployment {_fmt(unrate[-1].value)}%, Sahm indicator {_fmt(sahm, 2)} pp "
            f"({'at or above' if triggered else 'below'} the 0.50 trigger)"
        )
    return Block(
        id="labor",
        title="Labor",
        latest=[v for v in (data.latest("PAYEMS"), data.latest("UNRATE")) if v],
        indicators=indicators,
        charts=[c for c in (data.chart("UNRATE", "percent"),) if c],
        insight=Insight(text="; ".join(parts) + ".", inputs=inputs) if parts else None,
    )


def _growth(data: _Data) -> Block:
    gdp = data.points("GDPC1")
    growth = ind.annualized_growth(gdp)
    indicators, insight = [], None
    if growth is not None:
        quarter = f"Q{(gdp[-1].day.month - 1) // 3 + 1} {gdp[-1].day.year}"
        indicators.append(
            Indicator(
                term_id="real_gdp_growth_annualized",
                value=growth,
                unit="percent",
                as_of=gdp[-1].day,
                label="contraction" if growth < 0 else "expansion",
            )
        )
        insight = Insight(
            text=f"Real GDP {'shrank' if growth < 0 else 'grew'} {_fmt(abs(growth))}% "
            f"at an annual rate in {quarter}.",
            inputs=_refs(data.ref("GDPC1"), data.ref("GDPC1", 1)),
        )
    series = ind.annualized_growth_series(gdp)[-12:]
    return Block(
        id="growth",
        title="Growth",
        latest=[v for v in (data.latest("GDPC1"),) if v],
        indicators=indicators,
        charts=[_chart("real_gdp_growth_annualized", "percent", series, True)] if series else [],
        insight=insight,
    )


def _policy(data: _Data) -> Block:
    fed, pce = data.points("FEDFUNDS"), data.points("PCEPILFE")
    pce_yoy = ind.yoy_percent(pce)
    indicators, insight = [], None
    if fed and pce_yoy is not None:
        real = fed[-1].value - pce_yoy
        indicators.append(
            Indicator(
                term_id="real_fed_funds_rate",
                value=real,
                unit="pp",
                as_of=fed[-1].day,
                label="positive" if real > 0 else "negative" if real < 0 else "zero",
            )
        )
        insight = Insight(
            text=(
                f"Fed funds averaged {_fmt(fed[-1].value, 2)}% in {_month(fed[-1].day)}, "
                f"{_signed(real, 2, ' pp')} against core PCE inflation of {_fmt(pce_yoy)}%."
            ),
            inputs=_refs(data.ref("FEDFUNDS"), data.ref("PCEPILFE")),
        )
    return Block(
        id="policy",
        title="Policy rates",
        latest=[v for s in ("FEDFUNDS", "DGS2", "DGS10") if (v := data.latest(s))],
        indicators=indicators,
        charts=[c for c in (data.chart("FEDFUNDS", "percent"),) if c],
        insight=insight,
    )


def _curve(data: _Data) -> Block:
    spread = data.points("T10Y2Y", full_history=True)
    streak = ind.inversion_streak(spread)
    indicators, insight = [], None
    if streak is not None:
        state = "inverted" if streak.inverted else "positive"
        # A streak reaching the first stored observation may be longer than we can see.
        span = (
            f"throughout the data stored (since {streak.since.isoformat()})"
            if streak.since == spread[0].day
            else f"for {streak.observations} trading days, since {streak.since.isoformat()}"
        )
        indicators.append(
            Indicator(
                term_id="yield_curve_inversion",
                value=Decimal(streak.observations),
                unit="observations",
                as_of=spread[-1].day,
                label=state,
                since=streak.since,
            )
        )
        insight = Insight(
            text=(
                f"The 10Y-2Y spread is {_signed(spread[-1].value, 2, ' pp')} "
                f"({spread[-1].day.isoformat()}), {state} {span}."
            ),
            inputs=_refs(data.ref("T10Y2Y"), data.ref_on("T10Y2Y", streak.since)),
        )
    return Block(
        id="curve",
        title="Yield curve",
        latest=[v for v in (data.latest("T10Y2Y"),) if v],
        indicators=indicators,
        charts=[c for c in (data.chart("T10Y2Y", "pp", zero_line=True),) if c],
        insight=insight,
    )


def _risk(data: _Data) -> Block:
    hy, vix = data.points("BAMLH0A0HYM2", full_history=True), data.points("VIXCLS")
    one_year = [p for p in vix if vix and p.day > vix[-1].day - timedelta(days=365)]
    hy_pct, vix_pct = ind.percentile_rank(hy), ind.percentile_rank(one_year)
    indicators, parts = [], []
    if hy_pct is not None:
        indicators.append(
            Indicator(
                term_id="hy_oas_percentile",
                value=hy_pct,
                unit="percentile",
                as_of=hy[-1].day,
                label=ind.band(hy_pct),
            )
        )
        parts.append(
            f"High-yield spread {_fmt(hy[-1].value, 2)}%, {ind.band(hy_pct)} "
            f"({_fmt(hy_pct, 0)}th percentile since {hy[0].day.isoformat()})"
        )
    if vix_pct is not None:
        indicators.append(
            Indicator(
                term_id="vix_percentile_1y",
                value=vix_pct,
                unit="percentile",
                as_of=vix[-1].day,
                label=ind.band(vix_pct),
            )
        )
        parts.append(
            f"VIX {_fmt(vix[-1].value, 2)}, {ind.band(vix_pct)} "
            f"({_fmt(vix_pct, 0)}th percentile of 12 months)"
        )
    return Block(
        id="risk",
        title="Risk",
        latest=[v for s in ("BAMLH0A0HYM2", "VIXCLS") if (v := data.latest(s))],
        indicators=indicators,
        charts=[c for c in (data.chart("VIXCLS", "index"),) if c],
        insight=Insight(
            text="; ".join(parts) + ".", inputs=_refs(data.ref("BAMLH0A0HYM2"), data.ref("VIXCLS"))
        )
        if parts
        else None,
    )


MARKET_SYMBOLS = ("SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "XLE", "XLK")
BENCHMARK = "SPY"


# How the insight names a live quote's feed status (the badge shows it too).
LIVE_FEED_TEXT = {
    "live_single_venue": "live, IEX only",
    "end_of_day": "IEX close",
    "stale": "stale IEX quote",
}


def _markets(data: _Data) -> Block:
    """Universe ETFs: live IEX quotes (or daily closes for a past date), SPY's year and its
    distance from the 52-week high (M0.7, ADR-017)."""
    session, now = data.session, data.known_at
    calendar = market_calendar()
    ready = provider_ready(session)
    instruments = instruments_by_symbol(session, list(MARKET_SYMBOLS))
    tiles: list[PriceTile] = []
    if data.live:
        quotes = latest_quotes(session, instruments.values())
        for symbol in MARKET_SYMBOLS:
            stored = quotes.get(instruments[symbol]) if symbol in instruments else None
            q = quote_out(symbol, stored, now=now, calendar=calendar, ready=ready)
            tiles.append(
                PriceTile(
                    symbol=symbol,
                    feed_status=q.feed_status,
                    last=q.last,
                    change_pct=q.change_pct,
                    published_at=q.published_at,
                )
            )
    else:
        for symbol in MARKET_SYMBOLS:
            tiles.append(_close_tile(session, symbol, instruments.get(symbol), now, ready))
    indicators: list[Indicator] = []
    charts: list[Chart] = []
    insight = None
    spy = next(t for t in tiles if t.symbol == BENCHMARK)
    if BENCHMARK in instruments and spy.last is not None:
        history = price_history(
            session, instruments[BENCHMARK], known_at=now, last=spy.last, ready=ready
        )
        day = (spy.published_at or now).astimezone(NEW_YORK).date()
        below = history.pct_below_52w_high
        if spy.change_pct is not None:
            indicators.append(
                Indicator(
                    term_id="price_change_1d", value=spy.change_pct, unit="percent", as_of=day
                )
            )
        if below is not None:
            indicators.append(
                Indicator(term_id="pct_below_52w_high", value=below, unit="percent", as_of=day)
            )
        if history.closes:
            charts.append(
                Chart(
                    term_id="price_history",
                    unit="usd",
                    zero_line=False,
                    points=[ChartPoint(day=p.day, value=p.close) for p in history.closes],
                )
            )
        if spy.feed_status == "fixture":
            feed = "recorded fixture"
        elif data.live:
            feed = LIVE_FEED_TEXT.get(spy.feed_status, spy.feed_status)
        else:
            feed = "consolidated close"
        change = (
            f"{_signed(spy.change_pct, 2, '%')} on the day " if spy.change_pct is not None else ""
        )
        high_text = f"{_fmt(below, 1)}% below its 52-week high" if below else "at its 52-week high"
        insight = Insight(
            text=f"SPY {_fmt(spy.last, 2)}, {change}({feed}); {high_text}.",
            inputs=[InputRef(series_id=BENCHMARK, observation_date=day, vintage=day)],
        )
    return Block(
        id="markets",
        title="Markets",
        latest=[],
        indicators=indicators,
        charts=charts,
        insight=insight,
        prices=tiles,
    )


def _close_tile(
    session: Session, symbol: str, instrument: UUID | None, known_at: datetime, ready: bool
) -> PriceTile:
    """A past point in time: the latest raw close known then and its change on the day."""
    if instrument is None:
        return PriceTile(symbol=symbol, feed_status="unavailable")
    history = price_history(
        session,
        instrument,
        known_at=known_at,
        last=None,
        ready=ready,
        since=known_at - timedelta(days=10),
    )
    if history.last_close is None:
        return PriceTile(symbol=symbol, feed_status="unavailable")
    last, previous = history.last_close, history.previous_close
    return PriceTile(
        symbol=symbol,
        feed_status=history.feed_status,
        last=last.close,
        change_pct=change_percent(last.close, previous.close) if previous else None,
        published_at=end_of_day(last.day),
    )


BLOCKS: tuple[Callable[[_Data], Block], ...] = (
    _markets,
    _inflation,
    _labor,
    _growth,
    _policy,
    _curve,
    _risk,
)


@router.get("/overview")
def overview(
    session: SessionDep,
    known_at: Annotated[
        AwareDatetime | None, Query(description="Point in time (ADR-012); default now")
    ] = None,
) -> Overview:
    at: datetime = known_at or session.execute(select(func.now())).scalar_one()
    data = _Data(session, at, live=known_at is None)
    return Overview(
        known_at=at,
        market=market_state(market_calendar(), at) if known_at is None else None,
        blocks=[build(data) for build in BLOCKS],
        last_refresh_at=session.scalar(
            select(func.max(IngestionRun.finished_at)).where(
                IngestionRun.source_id == "fred", IngestionRun.status == "succeeded"
            )
        ),
    )
