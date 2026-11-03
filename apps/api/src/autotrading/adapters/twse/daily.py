"""Job `twse.daily` (M3.7, ADR-039 TW1-TW9): the Taiwan universe's latest session from the TWSE
OpenAPI, three times a day (07:40, 09:40 and 20:40 Singapore time).

fetch: STOCK_DAY_ALL, BWIBBU_d, MI_MARGN, TWT48U_ALL and the holiday schedule; the company file
too when a universe instrument is still missing, when STOCK_DAY_ALL names a four-digit code the
company file was never seen with (a new listing), or when asked (`companies`, weekly; M3.11,
ADR-042 SC2). Every file holds only the latest session, so a session no run catches is lost
(KI-27).
store, for the session D of STOCK_DAY_ALL:
- raw daily bars (price_bars, feed `twse`), public at the end of D in Taipei (ADR-012);
- exchange_measures: the price change and trade value of D; the P/E, P/B and dividend yield of
  BWIBBU_d when its date is D (its close must equal D's); the margin and short balances of
  MI_MARGN when the chain of balances dates it to D (TW6);
- cash and stock dividends of TWT48U_ALL whose ex-date is at most the next session;
- every listed company outside the universe (ADR-042 SC1, SC3): its raw bar, price change and
  trade value only, in one batch; the company file's changes in listed_companies;
- notes: no new session, sessions lost, a file not yet updated, a reference price no recorded
  action explains (TW9, universe only), a holiday schedule that differs from
  config/market_calendar_xtai.yaml.
A session already stored is unchanged; nothing is guessed.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, ClassVar, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.twse.client import (
    API_BASE,
    COMPANIES,
    DAY,
    EX_RIGHTS,
    HOLIDAYS,
    MARGIN,
    SOURCE_ID,
    VALUATION,
    TwseClient,
)
from autotrading.adapters.twse.instruments import (
    existing_instruments,
    resolve_instruments,
    resolve_listed,
)
from autotrading.db.models import DividendEvent, PriceBar, Source, SplitEvent
from autotrading.domain.market_calendar import MarketCalendar
from autotrading.domain.markets import TW
from autotrading.domain.provenance import LicenseStatus, Provenance, end_of_day
from autotrading.domain.splits import effective_at
from autotrading.domain.twse import (
    MARGIN_FIELDS,
    CompanyRow,
    DayRow,
    ExRightRow,
    MarginRow,
    closures,
    company_rows,
    day_rows,
    ex_right_rows,
    holiday_rows,
    margin_dating,
    margin_rows,
    reference_gap,
    session_of,
    valuation_rows,
)
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoredPayload,
    StoreResult,
    register_job,
)
from autotrading.ingestion.schedule import market_calendar
from autotrading.repositories.exchange_measures import (
    MeasureIn,
    insert_measures,
    latest_session,
    values_on,
)
from autotrading.repositories.listed import known_codes, listed_at, record_listed
from autotrading.repositories.prices import BarIn, PriceRepository
from autotrading.repositories.universe import TaiwanUniverse, taiwan_universe

ACTOR = "ingest:twse_openapi"
ZONE = "Asia/Taipei"
UNVERIFIED_CONFIDENCE = Decimal("0.9")
MARGIN_UNIT = "lots"
# Every four-digit STOCK_DAY_ALL code starting 1-9 is a company of the company file (checked on
# the recorded files); 00xx are funds, six-character codes are warrants, ETNs and the like.
COMPANY_CODE = re.compile(r"[1-9]\d{3}")


def _path(payload: StoredPayload) -> str:
    return payload.source_url.removeprefix(API_BASE)


def _json(payload: StoredPayload) -> Any:
    return json.loads(payload.content)


@register_job
class TwseDailyJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "twse.daily"
    feed_status: ClassVar[str] = "end_of_day"  # fixture for recorded test data
    data_mode: ClassVar[str] = "live"

    def client(self) -> TwseClient:
        return TwseClient()

    def universe(self) -> TaiwanUniverse:
        return taiwan_universe()

    def calendar(self) -> MarketCalendar:
        return market_calendar(TW.exchange)

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        with self.client() as client:
            fetched = [
                client.get(path, ctx.acquire)
                for path in (DAY, VALUATION, MARGIN, EX_RIGHTS, HOLIDAYS)
            ]
            if (
                self.params.get("companies")
                or self._missing(ctx.sessions)
                or self._new_listings(ctx.sessions, fetched[0])
            ):
                fetched.append(client.get(COMPANIES, ctx.acquire))
        return fetched

    def _missing(self, sessions: Callable[[], Session] | None) -> bool:
        """Whether a universe code has no instrument yet (the company file names them)."""
        if sessions is None:
            return True
        codes = self.universe().codes
        with sessions() as session:
            return len(existing_instruments(session, codes)) < len(codes)

    def _new_listings(self, sessions: Callable[[], Session] | None, day: FetchedPayload) -> bool:
        """Whether STOCK_DAY_ALL names a company code the company file was never seen with."""
        codes = {
            r.code for r in day_rows(json.loads(day.content)) if COMPANY_CODE.fullmatch(r.code)
        }
        if sessions is None:
            return True
        with sessions() as session:
            return bool(codes - known_codes(session))

    def store(self, ctx: StoreContext) -> StoreResult:
        session = ctx.session
        source = session.get_one(Source, SOURCE_ID)
        payloads = {_path(p): p for p in ctx.payloads}
        universe = self.universe()
        codes = set(universe.codes)
        day_payload = payloads[DAY]
        every = {r.code: r for r in day_rows(_json(day_payload))}
        days = {code: r for code, r in every.items() if code in codes}
        if not days:
            raise ValueError("STOCK_DAY_ALL lists none of the Taiwan universe")
        today = session_of(list(days.values()))
        companies = (
            {c.code: c for c in company_rows(_json(payloads[COMPANIES]))}
            if COMPANIES in payloads
            else {}
        )
        ids = resolve_instruments(
            session, universe.equities, universe.etfs, companies, at=day_payload.fetched_at
        )
        store = _Store(self, ctx, session, source, ids, set(universe.etfs), today)
        store.notes += store.session_notes(self.calendar())
        store.bars(days, day_payload)
        listed = self._listed(store, payloads, companies)
        self._listed_codes(store, every, listed, codes, day_payload)
        self._extra_codes(store, payloads, codes | set(listed), today)
        store.day_measures(days, day_payload)
        if VALUATION in payloads:
            store.valuation(payloads[VALUATION], days)
        if MARGIN in payloads:
            store.margin(payloads[MARGIN])
        if EX_RIGHTS in payloads:
            store.ex_rights(payloads[EX_RIGHTS], self.calendar())
        store.reference_checks(days)
        if HOLIDAYS in payloads:
            store.notes += _holiday_notes(payloads[HOLIDAYS], self.calendar())
        return StoreResult(
            inserted=store.inserted,
            unchanged=store.unchanged,
            conflicted=len(store.conflicts),
            notes=tuple(store.notes + store.conflicts),
        )

    def _listed(
        self,
        store: "_Store",
        payloads: Mapping[str, StoredPayload],
        companies: Mapping[str, CompanyRow],
    ) -> dict[str, UUID]:
        """code -> instrument of every listed company (ADR-042 SC1, SC2): from the company file
        when this run fetched it (recording its changes), else as last recorded."""
        session = store.session
        if not companies:
            return {code: c.instrument_id for code, c in listed_at(session).items()}
        file = payloads[COMPANIES]
        ids = resolve_listed(session, companies, at=file.fetched_at)
        inserted, unchanged = record_listed(
            session, companies, ids, file, store.source, store.ctx.run_id, actor=ACTOR
        )
        store.count(inserted, unchanged, [])
        if inserted:
            store.notes.append(
                f"company file: {inserted} change(s) recorded among {len(companies)} companies"
            )
        return ids

    def _listed_codes(
        self,
        store: "_Store",
        every: Mapping[str, DayRow],
        listed: Mapping[str, UUID],
        universe: set[str],
        payload: StoredPayload,
    ) -> None:
        """The raw bar, price change and trade value of every listed company outside the
        universe (ADR-042 SC3), in one batch; no valuation, margin or TW9 note of theirs."""
        days = {code: row for code, row in every.items() if code in listed and code not in universe}
        if not days:
            return
        ids = {code: listed[code] for code in days}
        rows = _Store(self, store.ctx, store.session, store.source, ids, set(), store.today)
        rows.bars(days, payload, summarize=True)
        rows.day_measures(days, payload)
        store.count(rows.inserted, rows.unchanged, rows.conflicts)
        store.notes += rows.notes

    def _extra_codes(
        self,
        store: "_Store",
        payloads: Mapping[str, StoredPayload],
        stored: set[str],
        today: date,
    ) -> None:
        """Closes and ex-rights of the codes held outside the universe that are not listed
        companies (ADR-041 H6; funds, mostly), under the instruments the Holdings page created;
        no measure of theirs is stored."""
        extra = sorted(set(map(str, self.params.get("extra_codes") or [])) - stored)
        if not extra:
            return
        listed = {r.code: r for r in day_rows(_json(payloads[DAY])) if r.code in extra}
        ids = existing_instruments(store.session, list(listed))
        rows = {code: listed[code] for code in ids}
        if rows and session_of(list(rows.values())) == today:
            held = _Store(self, store.ctx, store.session, store.source, ids, set(), today)
            held.bars(rows, payloads[DAY])
            if EX_RIGHTS in payloads:
                held.ex_rights(payloads[EX_RIGHTS], self.calendar())
            store.count(held.inserted, held.unchanged, held.conflicts)
            store.notes += held.notes
        if len(listed) < len(extra):
            store.notes.append(
                f"{len(extra) - len(listed)} held code(s) not in STOCK_DAY_ALL: TPEx listings "
                "are not supported"
            )


class _Store:
    """One run's writes for session `today`, with the counts and notes."""

    def __init__(
        self,
        job: TwseDailyJob,
        ctx: StoreContext,
        session: Session,
        source: Source,
        ids: Mapping[str, UUID],
        etfs: set[str],
        today: date,
    ) -> None:
        self.job = job
        self.ctx = ctx
        self.session = session
        self.source = source
        self.ids = ids
        self.etfs = etfs
        self.today = today
        self.published = end_of_day(today, ZONE)
        self.inserted = 0
        self.unchanged = 0
        self.conflicts: list[str] = []
        self.notes: list[str] = []
        self.calendar = job.calendar()

    # ---------- shared ----------

    def provenance(
        self,
        payload: StoredPayload,
        day: date,
        *,
        published_at: datetime | None = None,
        confidence: Decimal = Decimal(1),
    ) -> Provenance:
        start = datetime.combine(day, time(0, 0), TW.zone)
        return Provenance(
            source_id=self.source.id,
            source_tier=self.source.tier,
            source_url=payload.source_url,
            published_at=published_at or end_of_day(day, ZONE),
            published_at_precision="day",
            ingested_at=payload.fetched_at,
            effective_from=start,
            effective_to=start + timedelta(days=1),
            as_of=start,
            license_status=cast(LicenseStatus, self.source.license_status),
            confidence=float(confidence),
            source_timezone=ZONE,
            ingestion_run_id=self.ctx.run_id,
            raw_payload_sha256=payload.sha256,
        )

    def count(self, inserted: int, unchanged: int, conflicts: Iterable[str]) -> None:
        self.inserted += inserted
        self.unchanged += unchanged
        self.conflicts += list(conflicts)

    def _previous_closes(self) -> dict[str, tuple[date, Decimal]]:
        """code -> (session, close) of the latest raw bar stored before today."""
        found: dict[str, tuple[date, Decimal]] = {}
        for code, instrument_id in self.ids.items():
            bar = self.session.scalars(
                select(PriceBar)
                .where(
                    PriceBar.instrument_id == instrument_id,
                    PriceBar.adjustment == "raw",
                    PriceBar.superseded_at.is_(None),
                    PriceBar.bar_date < self.today,
                )
                .order_by(PriceBar.bar_date.desc())
                .limit(1)
            ).first()
            if bar is not None:
                found[code] = (bar.bar_date, bar.close)
        return found

    def _stored_sessions(self) -> set[date]:
        return set(
            self.session.scalars(
                select(PriceBar.bar_date).where(
                    PriceBar.instrument_id.in_(list(self.ids.values())),
                    PriceBar.adjustment == "raw",
                    PriceBar.superseded_at.is_(None),
                )
            )
        )

    # ---------- sessions ----------

    def adjacent(self, earlier: date) -> bool:
        """Whether `earlier` is the session right before today in the TWSE calendar: no
        calendar session lies between them (a lost session breaks the chain)."""
        between = self.calendar.sessions_between(
            earlier + timedelta(days=1), self.today - timedelta(days=1)
        )
        return not between

    def session_notes(self, calendar: MarketCalendar) -> list[str]:
        stored = self._stored_sessions()
        if self.today in stored:
            return [f"no new session: TWSE still serves {self.today}"]
        before = [d for d in stored if d < self.today]
        if not before:
            return [f"first session stored: {self.today}"]
        last = max(before)
        lost = [
            s.day
            for s in calendar.sessions_between(
                last + timedelta(days=1), self.today - timedelta(days=1)
            )
        ]
        if not lost:
            return []
        days = ", ".join(str(d) for d in lost)
        return [
            f"sessions lost: {days} (the OpenAPI serves only the latest session; no run "
            "caught them)"
        ]

    # ---------- STOCK_DAY_ALL ----------

    def bars(
        self, days: Mapping[str, DayRow], payload: StoredPayload, *, summarize: bool = False
    ) -> None:
        """One raw bar per code that traded; a code without a trade gets a note (one note for
        all of them when `summarize`)."""
        bar_time = datetime.combine(self.today, time(0, 0), TW.zone)
        bars = []
        quiet: list[str] = []
        for code, row in days.items():
            if code not in self.ids:
                continue
            if None in (row.open, row.high, row.low, row.close):
                quiet.append(code)
                continue
            bars.append(
                BarIn(
                    instrument_id=self.ids[code],
                    symbol=code,
                    adjustment="raw",
                    bar_time=bar_time,
                    open=cast(Decimal, row.open),
                    high=cast(Decimal, row.high),
                    low=cast(Decimal, row.low),
                    close=cast(Decimal, row.close),
                    volume=int(row.volume),
                    vwap=None,
                    trade_count=int(row.transactions),
                    feed="twse",
                    feed_status=self.job.feed_status,
                    provenance=self.provenance(payload, self.today),
                    bar_date=self.today,
                )
            )
        result = PriceRepository(self.session).insert_bars(bars, actor=ACTOR)
        self.count(result.inserted, result.unchanged, result.conflicts)
        if summarize and quiet:
            self.notes.append(f"{len(quiet)} listed code(s) had no trade on {self.today}: no bar")
        elif quiet:
            self.notes += [f"{code} {self.today}: no trade, no bar" for code in quiet]

    def measure(
        self,
        code: str,
        day: date,
        measure_id: str,
        value: Decimal | None,
        unit: str,
        payload: StoredPayload,
        detail: str | None = None,
        confidence: Decimal = Decimal(1),
    ) -> MeasureIn | None:
        if value is None or code not in self.ids:
            return None
        return MeasureIn(
            instrument_id=self.ids[code],
            symbol=code,
            session_date=day,
            measure_id=measure_id,
            value=value,
            unit=unit,
            detail=detail,
            data_mode=self.job.data_mode,
            provenance=self.provenance(payload, day, confidence=confidence),
        )

    def insert(self, items: Iterable[MeasureIn | None]) -> None:
        result = insert_measures(self.session, [i for i in items if i is not None], actor=ACTOR)
        self.count(result.inserted, result.unchanged, result.conflicts)

    def day_measures(self, days: Mapping[str, DayRow], payload: StoredPayload) -> None:
        self.insert(
            item
            for code, row in days.items()
            for item in (
                self.measure(code, self.today, "price_change", row.change, "TWD", payload),
                self.measure(code, self.today, "trade_value", row.value, "TWD", payload),
            )
        )

    # ---------- BWIBBU_d ----------

    def valuation(self, payload: StoredPayload, days: Mapping[str, DayRow]) -> None:
        rows = [r for r in valuation_rows(_json(payload)) if r.code in self.ids]
        if not rows:
            return
        found = {r.session for r in rows}
        if found != {self.today}:
            dates = ", ".join(str(d) for d in sorted(found))
            self.notes.append(
                f"BWIBBU_d is for {dates}, not {self.today}: not stored (a later run reads it)"
            )
            return
        items: list[MeasureIn | None] = []
        for row in rows:
            close = days[row.code].close if row.code in days else None
            if row.close != close:
                self.notes.append(
                    f"{row.code} {self.today}: BWIBBU_d close {row.close} is not the session "
                    f"close {close}; valuation not stored"
                )
                continue
            basis = (
                f"earnings and book value of {row.fiscal_quarter}" if row.fiscal_quarter else None
            )
            year = f"dividends of {row.dividend_year}" if row.dividend_year else None
            items += [
                self.measure(
                    row.code, self.today, "exchange_pe_ratio", row.pe, "x", payload, basis
                ),
                self.measure(
                    row.code, self.today, "exchange_pb_ratio", row.pb, "x", payload, basis
                ),
                self.measure(
                    row.code,
                    self.today,
                    "exchange_dividend_yield",
                    row.dividend_yield,
                    "percent",
                    payload,
                    year,
                ),
            ]
        self.insert(items)

    # ---------- MI_MARGN ----------

    def margin(self, payload: StoredPayload) -> None:
        rows = [r for r in margin_rows(_json(payload)) if r.code in self.ids]
        if not rows:
            self.notes.append("MI_MARGN lists none of the Taiwan universe")
            return
        ids = list(self.ids.values())
        before = latest_session(self.session, ids, "margin_balance", before=self.today)
        previous: dict[str, dict[str, Decimal]] | None = None
        adjacent = False
        if before is not None:
            stored = values_on(self.session, ids, ["margin_balance", "short_balance"], before)
            code_of = {v: k for k, v in self.ids.items()}
            previous = {code_of[i]: v for i, v in stored.items()}
            adjacent = self.adjacent(before)
        dating = margin_dating(rows, previous, adjacent=adjacent)
        if not dating.accepted:
            self.notes.append(
                f"MI_MARGN still shows an earlier session than {self.today}: not stored (a "
                "later run reads it)"
            )
            return
        if dating.status == "unverified":
            self.notes.append(
                f"MI_MARGN dated {self.today} by the run's STOCK_DAY_ALL; the chain of balances "
                "is checked at the next session"
            )
        for code in dating.mismatched:
            self.notes.append(
                f"{code} {self.today}: MI_MARGN previous balances differ from the stored "
                f"{before} balances (stored with confidence {UNVERIFIED_CONFIDENCE})"
            )
        self.insert(
            item
            for row in rows
            for item in self._margin_items(row, payload, dating.status, dating.mismatched)
        )

    def _margin_items(
        self, row: MarginRow, payload: StoredPayload, status: str, mismatched: tuple[str, ...]
    ) -> list[MeasureIn | None]:
        sure = status == "verified" or (status == "partial" and row.code not in mismatched)
        confidence = Decimal(1) if sure else UNVERIFIED_CONFIDENCE
        return [
            self.measure(
                row.code,
                self.today,
                measure_id,
                row.values[measure_id],
                MARGIN_UNIT,
                payload,
                row.note if measure_id == "margin_balance" else None,
                confidence,
            )
            for measure_id in MARGIN_FIELDS.values()
        ]

    # ---------- TWT48U_ALL ----------

    def ex_rights(self, payload: StoredPayload, calendar: MarketCalendar) -> None:
        upcoming = calendar.next_open(end_of_day(self.today, ZONE))
        horizon = upcoming.astimezone(TW.zone).date()
        rows = [
            r for r in ex_right_rows(_json(payload)) if r.code in self.ids and r.ex_date <= horizon
        ]
        for row in rows:
            if row.subscription_ratio:
                self.notes.append(
                    f"{row.code} {row.ex_date}: a rights offering (認購率 "
                    f"{row.subscription_ratio}) is not modelled; the reference price check "
                    "flags its effect"
                )
            if row.cash:
                self._dividend(row, payload)
            if row.stock_ratio:
                self._stock_dividend(row, payload)

    def _event(self, row: ExRightRow, payload: StoredPayload) -> dict[str, Any]:
        start = effective_at(row.ex_date, TW.zone)
        return {
            "instrument_id": self.ids[row.code],
            "symbol": row.code,
            "ex_date": row.ex_date,
            "source_id": self.source.id,
            "source_tier": self.source.tier,
            "source_url": payload.source_url,
            "published_at": start,
            "published_at_precision": "day",
            "ingested_at": payload.fetched_at,
            "effective_from": start,
            "effective_to": None,
            "as_of": start,
            "license_status": self.source.license_status,
            "confidence": Decimal(1),
            "source_timezone": ZONE,
            "ingestion_run_id": self.ctx.run_id,
            "raw_payload_sha256": payload.sha256,
        }

    def _dividend(self, row: ExRightRow, payload: StoredPayload) -> None:
        stored = self.session.scalars(
            select(DividendEvent).where(
                DividendEvent.instrument_id == self.ids[row.code],
                DividendEvent.ex_date == row.ex_date,
                DividendEvent.special.is_(False),
            )
        ).first()
        if stored is not None:
            if stored.rate == row.cash:
                self.unchanged += 1
            else:
                self.conflicts.append(
                    f"{row.code} {row.ex_date}: cash dividend {row.cash} differs from the stored "
                    f"{stored.rate}"
                )
            return
        self.session.add(
            DividendEvent(**self._event(row, payload), rate=row.cash, special=False, foreign=False)
        )
        self.session.flush()
        self.inserted += 1

    def _stock_dividend(self, row: ExRightRow, payload: StoredPayload) -> None:
        ratio = 1 + cast(Decimal, row.stock_ratio)
        stored = self.session.scalars(
            select(SplitEvent).where(
                SplitEvent.instrument_id == self.ids[row.code],
                SplitEvent.ex_date == row.ex_date,
            )
        ).first()
        if stored is not None:
            if stored.new_rate / stored.old_rate == ratio:
                self.unchanged += 1
            else:
                self.conflicts.append(
                    f"{row.code} {row.ex_date}: stock dividend {row.stock_ratio} differs from "
                    "the stored one"
                )
            return
        self.session.add(
            SplitEvent(
                **self._event(row, payload),
                old_rate=Decimal(1),
                new_rate=ratio,
                kind="stock_dividend",
            )
        )
        self.session.flush()
        self.inserted += 1
        self.notes.append(
            f"{row.code} {row.ex_date}: stock dividend ratio {row.stock_ratio} stored as "
            f"{ratio} shares per share (KI-28: check against the reference price)"
        )

    # ---------- reference price (TW9) ----------

    def reference_checks(self, days: Mapping[str, DayRow]) -> None:
        closes = self._previous_closes()
        for code, row in days.items():
            previous = closes.get(code)
            if row.close is None or row.change is None or previous is None:
                continue
            if not self.adjacent(previous[0]):
                continue  # a lost session in between: TWSE's reference is that session's close
            cash, stock = self._actions_on(code)
            gap = reference_gap(
                code,
                self.today,
                row.close,
                row.change,
                previous[0],
                previous[1],
                etf=code in self.etfs,
                cash=cash,
                stock_ratio=stock,
            )
            if gap is not None:
                self.notes.append(gap.note())

    def _actions_on(self, code: str) -> tuple[Decimal, Decimal]:
        instrument_id = self.ids[code]
        cash = sum(
            (
                d.rate
                for d in self.session.scalars(
                    select(DividendEvent).where(
                        DividendEvent.instrument_id == instrument_id,
                        DividendEvent.ex_date == self.today,
                    )
                )
            ),
            Decimal(0),
        )
        stock = sum(
            (
                s.new_rate / s.old_rate - 1
                for s in self.session.scalars(
                    select(SplitEvent).where(
                        SplitEvent.instrument_id == instrument_id,
                        SplitEvent.ex_date == self.today,
                    )
                )
            ),
            Decimal(0),
        )
        return cash, stock


def _holiday_notes(payload: StoredPayload, calendar: MarketCalendar) -> list[str]:
    rows = holiday_rows(_json(payload))
    if not rows:
        return []
    years = {r.day.year for r in rows}
    published = closures(rows)
    configured = {d for d in calendar.holidays if d.year in years}
    if published == configured:
        return []
    added = ", ".join(str(d) for d in sorted(published - configured)) or "none"
    removed = ", ".join(str(d) for d in sorted(configured - published)) or "none"
    return [
        "the TWSE holiday schedule differs from config/market_calendar_xtai.yaml: "
        f"closures not in the file: {added}; in the file but not published: {removed}"
    ]
