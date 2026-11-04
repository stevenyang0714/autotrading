"""The writes the FinMind jobs share (M3.7b, ADR-040 TW18, TW19, TW23, TW24).

- Rows go to the tables the TWSE adapter fills: `price_bars` (feed finmind), `exchange_measures`,
  `dividend_events` and `split_events`, with source finmind (tier 2).
- A session stored for the first time is public at the end of its Taipei day; a later fetch
  that shows a different value for a session already stored is public at the end of the fetch
  day in Taipei, so it becomes a revision instead of a conflict (TW18, as ALFRED vintages).
- A session that has a current `twse_openapi` row is never written (TW24); on those sessions
  the FinMind values are compared with the stored ones instead (TW19): all equal gives the
  batch confidence 1.0, any difference 0.9 and a note naming it.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.finmind.client import SOURCE_ID
from autotrading.adapters.twse.client import SOURCE_ID as TWSE_SOURCE_ID
from autotrading.adapters.twse.instruments import existing_instruments
from autotrading.db.models import DividendEvent, PriceBar, Source, SplitEvent
from autotrading.domain.finmind import (
    FLOW_UNITS,
    SHAREHOLDING_UNITS,
    DividendResult,
    FlowDay,
    MarginDay,
    ShareholdingDay,
)
from autotrading.domain.markets import TW
from autotrading.domain.provenance import LicenseStatus, Provenance, end_of_day
from autotrading.domain.splits import effective_at
from autotrading.domain.twse import MARGIN_FIELDS, DayRow, ValuationRow
from autotrading.ingestion.job import StoreContext, StoredPayload
from autotrading.repositories.exchange_measures import MeasureIn, current_values, insert_measures
from autotrading.repositories.prices import BarIn, PriceRepository

ACTOR = "ingest:finmind"
ZONE = "Asia/Taipei"
VALUATION_IDS = ("exchange_pe_ratio", "exchange_pb_ratio", "exchange_dividend_yield")
MARGIN_IDS = tuple(MARGIN_FIELDS.values())
CHECKED_CONFIDENCE = Decimal(1)
UNCHECKED_CONFIDENCE = Decimal("0.9")
MAX_NOTED_DIFFERENCES = 10


class Writer:
    """One run's writes for a set of codes, with the counts and notes."""

    def __init__(
        self,
        ctx: StoreContext,
        codes: Iterable[str],
        *,
        feed_status: str,
        data_mode: str,
    ) -> None:
        self.ctx = ctx
        self.session: Session = ctx.session
        self.source = self.session.get_one(Source, SOURCE_ID)
        self.feed_status = feed_status
        self.data_mode = data_mode
        self.ids = existing_instruments(self.session, codes)
        self.inserted = 0
        self.unchanged = 0
        self.conflicts: list[str] = []
        self.notes: list[str] = []
        self.differences: list[str] = []

    # ---------- provenance ----------

    def provenance(
        self, payload: StoredPayload, day: date, *, published_at: datetime, confidence: Decimal
    ) -> Provenance:
        start = datetime.combine(day, time(0, 0), TW.zone)
        return Provenance(
            source_id=self.source.id,
            source_tier=self.source.tier,
            source_url=payload.source_url,
            published_at=published_at,
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

    @staticmethod
    def fetch_day(payload: StoredPayload) -> date:
        return payload.fetched_at.astimezone(TW.zone).date()

    def published(
        self,
        current: Mapping[tuple[UUID, str, date], tuple[Decimal, str]],
        key: tuple[UUID, str, date],
        value: Decimal,
        payload: StoredPayload,
    ) -> datetime:
        """TW18: the end of the session's day, or of the fetch day for a changed value."""
        found = current.get(key)
        if found is not None and found[0] != value:
            return end_of_day(self.fetch_day(payload), ZONE)
        return end_of_day(key[2], ZONE)

    def count(self, inserted: int, unchanged: int, conflicts: Iterable[str]) -> None:
        self.inserted += inserted
        self.unchanged += unchanged
        self.conflicts += list(conflicts)

    def confidence(self) -> Decimal:
        return UNCHECKED_CONFIDENCE if self.differences else CHECKED_CONFIDENCE

    def finish_notes(self) -> list[str]:
        if self.differences:
            shown = "; ".join(self.differences[:MAX_NOTED_DIFFERENCES])
            more = len(self.differences) - MAX_NOTED_DIFFERENCES
            tail = f" (+{more} more)" if more > 0 else ""
            return [
                *self.notes,
                f"FinMind differs from the stored TWSE values on {len(self.differences)} "
                f"field(s), batch stored with confidence {UNCHECKED_CONFIDENCE}: {shown}{tail}",
            ]
        return self.notes

    # ---------- measures ----------

    def _measure_items(
        self,
        code: str,
        payload: StoredPayload,
        rows: Sequence[tuple[date, str, Decimal, str, str | None]],
        *,
        twse_primary: bool,
    ) -> None:
        """Store (session, measure id, value, unit, detail) rows of one code: TWSE sessions are
        compared and skipped when `twse_primary` (TW24), other rows versioned per TW18."""
        instrument_id = self.ids.get(code)
        if instrument_id is None or not rows:
            return
        sessions = [r[0] for r in rows]
        measure_ids = sorted({r[1] for r in rows})
        current = current_values(
            self.session,
            [instrument_id],
            measure_ids,
            since=min(sessions),
            until=max(sessions),
        )
        items: list[MeasureIn] = []
        confidence = self.confidence()
        for session_date, measure_id, value, unit, detail in rows:
            key = (instrument_id, measure_id, session_date)
            found = current.get(key)
            if found is not None and found[1] == TWSE_SOURCE_ID and twse_primary:
                if found[0] != value:
                    self.differences.append(
                        f"{code} {session_date} {measure_id}: FinMind {value} vs TWSE {found[0]}"
                    )
                continue
            items.append(
                MeasureIn(
                    instrument_id=instrument_id,
                    symbol=code,
                    session_date=session_date,
                    measure_id=measure_id,
                    value=value,
                    unit=unit,
                    detail=detail,
                    data_mode=self.data_mode,
                    provenance=self.provenance(
                        payload,
                        session_date,
                        published_at=self.published(current, key, value, payload),
                        confidence=confidence,
                    ),
                )
            )
        result = insert_measures(self.session, items, actor=ACTOR)
        self.count(result.inserted, result.unchanged, result.conflicts)

    def compare_only(self, code: str, rows: Sequence[tuple[date, str, Decimal]]) -> None:
        """TW19 for a batch that is stored later: note the differences on TWSE sessions."""
        instrument_id = self.ids.get(code)
        if instrument_id is None or not rows:
            return
        current = current_values(
            self.session,
            [instrument_id],
            sorted({r[1] for r in rows}),
            since=min(r[0] for r in rows),
            until=max(r[0] for r in rows),
        )
        for session_date, measure_id, value in rows:
            found = current.get((instrument_id, measure_id, session_date))
            if found is not None and found[1] == TWSE_SOURCE_ID and found[0] != value:
                self.differences.append(
                    f"{code} {session_date} {measure_id}: FinMind {value} vs TWSE {found[0]}"
                )

    def margin(self, code: str, days: Sequence[MarginDay], payload: StoredPayload) -> None:
        self._measure_items(
            code,
            payload,
            [
                (
                    d.session,
                    measure_id,
                    d.values[measure_id],
                    "lots",
                    d.note if measure_id == "margin_balance" else None,
                )
                for d in days
                for measure_id in MARGIN_IDS
            ],
            twse_primary=True,
        )

    def valuation(self, code: str, rows: Sequence[ValuationRow], payload: StoredPayload) -> None:
        detail = "FinMind TaiwanStockPER"
        self._measure_items(
            code,
            payload,
            [
                (r.session, measure_id, value, unit, detail)
                for r in rows
                for measure_id, value, unit in (
                    ("exchange_pe_ratio", r.pe, "x"),
                    ("exchange_pb_ratio", r.pb, "x"),
                    ("exchange_dividend_yield", r.dividend_yield, "percent"),
                )
                if value is not None
            ],
            twse_primary=True,
        )

    def day_measures(self, code: str, rows: Sequence[DayRow], payload: StoredPayload) -> None:
        self._measure_items(
            code,
            payload,
            [
                (r.session, measure_id, value, "TWD", None)
                for r in rows
                for measure_id, value in (("price_change", r.change), ("trade_value", r.value))
                if value is not None
            ],
            twse_primary=True,
        )

    def flows(self, code: str, days: Sequence[FlowDay], payload: StoredPayload) -> None:
        self._measure_items(
            code,
            payload,
            [
                (
                    d.session,
                    measure_id,
                    d.values[measure_id],
                    FLOW_UNITS[measure_id],
                    ", ".join(d.groups),
                )
                for d in days
                for measure_id in FLOW_UNITS
            ],
            twse_primary=False,
        )

    def shareholding(
        self, code: str, days: Sequence[ShareholdingDay], payload: StoredPayload
    ) -> None:
        self._measure_items(
            code,
            payload,
            [
                (d.session, measure_id, d.values[measure_id], SHAREHOLDING_UNITS[measure_id], None)
                for d in days
                for measure_id in SHAREHOLDING_UNITS
            ],
            twse_primary=False,
        )

    # ---------- bars ----------

    def _current_bars(self, instrument_id: UUID, since: date, until: date) -> dict[date, PriceBar]:
        rows = self.session.scalars(
            select(PriceBar).where(
                PriceBar.instrument_id == instrument_id,
                PriceBar.adjustment == "raw",
                PriceBar.superseded_at.is_(None),
                PriceBar.bar_date >= since,
                PriceBar.bar_date <= until,
            )
        )
        return {bar.bar_date: bar for bar in rows}

    def bars(self, code: str, rows: Sequence[DayRow], payload: StoredPayload) -> list[DayRow]:
        """Store the closes of sessions no TWSE bar covers; returns the rows stored (for the
        matching day measures)."""
        instrument_id = self.ids.get(code)
        if instrument_id is None or not rows:
            return []
        stored = self._current_bars(
            instrument_id, min(r.session for r in rows), max(r.session for r in rows)
        )
        kept: list[DayRow] = []
        bars: list[BarIn] = []
        confidence = self.confidence()
        for row in rows:
            if None in (row.open, row.high, row.low, row.close) or cast(Decimal, row.close) <= 0:
                self.notes.append(f"{code} {row.session}: no trade, no bar")
                continue
            close = cast(Decimal, row.close)
            existing = stored.get(row.session)
            if existing is not None and existing.source_id == TWSE_SOURCE_ID:
                if existing.close != close or existing.volume != int(row.volume):
                    self.differences.append(
                        f"{code} {row.session} close/volume: FinMind {close}/{int(row.volume)} "
                        f"vs TWSE {existing.close}/{existing.volume}"
                    )
                continue
            published = end_of_day(row.session, ZONE)
            if existing is not None and existing.close != close:
                published = end_of_day(self.fetch_day(payload), ZONE)  # TW18: a revision
            bars.append(
                BarIn(
                    instrument_id=instrument_id,
                    symbol=code,
                    adjustment="raw",
                    bar_time=datetime.combine(row.session, time(0, 0), TW.zone),
                    open=cast(Decimal, row.open),
                    high=cast(Decimal, row.high),
                    low=cast(Decimal, row.low),
                    close=close,
                    volume=int(row.volume),
                    vwap=None,
                    trade_count=int(row.transactions),
                    feed="finmind",
                    feed_status=self.feed_status,
                    provenance=self.provenance(
                        payload, row.session, published_at=published, confidence=confidence
                    ),
                    bar_date=row.session,
                )
            )
            kept.append(row)
        result = PriceRepository(self.session).insert_bars(bars, actor=ACTOR)
        self.count(result.inserted, result.unchanged, result.conflicts)
        return kept

    # ---------- dividends (TW20) ----------

    def reference_prices(
        self, code: str, results: Sequence[DividendResult], payload: StoredPayload
    ) -> None:
        """The reference price of every ex-date with prices, whatever its kind (息, 權 or 權息):
        `ex_reference_price`, which the Taiwan screens' returns use across the ex-date (M3.11,
        ADR-042 SC6)."""
        self._measure_items(
            code,
            payload,
            [
                (r.ex_date, "ex_reference_price", r.reference_price, "TWD", r.kind)
                for r in results
                if r.reference_price > 0 and r.before_price > 0
            ],
            twse_primary=False,
        )

    def dividends(
        self, code: str, results: Sequence[DividendResult], payload: StoredPayload
    ) -> None:
        instrument_id = self.ids.get(code)
        if instrument_id is None:
            return
        for result in results:
            if not result.accepted:
                if result.note:
                    self.notes.append(result.note)
                continue
            if result.cash is not None:
                self._cash(instrument_id, code, result, payload)
            if result.stock_ratio is not None:
                self._stock(instrument_id, code, result, payload)

    def _event(
        self, instrument_id: UUID, code: str, ex_date: date, payload: StoredPayload
    ) -> dict[str, Any]:
        start = effective_at(ex_date, TW.zone)
        return {
            "instrument_id": instrument_id,
            "symbol": code,
            "ex_date": ex_date,
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
            "confidence": CHECKED_CONFIDENCE,
            "source_timezone": ZONE,
            "ingestion_run_id": self.ctx.run_id,
            "raw_payload_sha256": payload.sha256,
        }

    def _cash(
        self, instrument_id: UUID, code: str, result: DividendResult, payload: StoredPayload
    ) -> None:
        stored = self.session.scalars(
            select(DividendEvent).where(
                DividendEvent.instrument_id == instrument_id,
                DividendEvent.ex_date == result.ex_date,
                DividendEvent.special.is_(False),
            )
        ).first()
        if stored is not None:
            if stored.rate == result.cash:
                self.unchanged += 1
            else:
                self.conflicts.append(
                    f"{code} {result.ex_date}: FinMind cash dividend {result.cash} differs from "
                    f"the stored {stored.rate} ({stored.source_id})"
                )
            return
        self.session.add(
            DividendEvent(
                **self._event(instrument_id, code, result.ex_date, payload),
                rate=result.cash,
                special=False,
                foreign=False,
            )
        )
        self.session.flush()
        self.inserted += 1

    def _stock(
        self, instrument_id: UUID, code: str, result: DividendResult, payload: StoredPayload
    ) -> None:
        ratio = 1 + cast(Decimal, result.stock_ratio)
        stored = self.session.scalars(
            select(SplitEvent).where(
                SplitEvent.instrument_id == instrument_id, SplitEvent.ex_date == result.ex_date
            )
        ).first()
        if stored is not None:
            if (stored.new_rate / stored.old_rate).quantize(Decimal("0.0001")) == ratio:
                self.unchanged += 1
            else:
                self.conflicts.append(
                    f"{code} {result.ex_date}: FinMind stock dividend {result.stock_ratio} differs "
                    f"from the stored {stored.new_rate / stored.old_rate - 1} ({stored.source_id})"
                )
            return
        self.session.add(
            SplitEvent(
                **self._event(instrument_id, code, result.ex_date, payload),
                old_rate=Decimal(1),
                new_rate=ratio,
                kind="stock_dividend",
            )
        )
        self.session.flush()
        self.inserted += 1
