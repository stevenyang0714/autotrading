"""Job `alpaca.daily_bars` (M0.7, ADR-017): consolidated (SIP) daily bars, raw and
split-adjusted, for the universe.

fetch: split events in the window (corporate actions), raw bars for the window, and
       split-adjusted bars for the window. A symbol that split in the window gets its whole
       split-adjusted history again, from BACKFILL_START, because a split re-bases all earlier
       prices. Bars page by next_page_token.
store: raw bars count as public at the end of their New York day (date-only, ADR-012);
       split-adjusted bars as of when they were fetched. Both are versioned (apply_versions).
"""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, cast
from uuid import UUID

from autotrading.adapters.alpaca.client import AlpacaClient
from autotrading.adapters.alpaca.snapshots import parse_time
from autotrading.adapters.alpaca.symbols import SOURCE_ID, resolve_instruments
from autotrading.db.models import Source
from autotrading.domain.market_calendar import NEW_YORK as _NEW_YORK
from autotrading.domain.prices import FeedStatus
from autotrading.domain.provenance import LicenseStatus, Provenance, TimePrecision, end_of_day
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoredPayload,
    StoreResult,
    register_job,
)
from autotrading.repositories.prices import BarIn, PriceRepository

ACTOR = f"ingest:{SOURCE_ID}"
BACKFILL_START = "2016-01-01"
PAGE_LIMIT = "10000"


def bars_params(symbols: list[str], adjustment: str, start: str, end: str | None) -> dict[str, str]:
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "adjustment": adjustment,
        "feed": "sip",
        "start": start,
        "limit": PAGE_LIMIT,
    }
    if end:
        params["end"] = end
    return params


def split_symbols(content: bytes) -> set[str]:
    actions = json.loads(content).get("corporate_actions") or {}
    return {
        str(action["symbol"]).upper()
        for kind in ("forward_splits", "reverse_splits")
        for action in actions.get(kind) or []
    }


def adjustment_of(url: str) -> str | None:
    marker = "adjustment="
    if "/v2/stocks/bars" not in url or marker not in url:
        return None
    return url.split(marker, 1)[1].split("&", 1)[0]


@register_job
class AlpacaDailyBarsJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "alpaca.daily_bars"
    # Daily bars are closes; recorded fixtures override it with "fixture" (ADR-006).
    feed_status: ClassVar[FeedStatus] = "end_of_day"

    def client(self) -> AlpacaClient:
        return AlpacaClient.from_settings()

    @property
    def symbols(self) -> list[str]:
        return [str(s).upper() for s in self.params["symbols"]]

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        start, end = str(self.params["start"]), self.params.get("end")
        payloads: list[FetchedPayload] = []
        with self.client() as client:
            actions = client.get(
                "/v1/corporate-actions",
                {
                    "symbols": ",".join(self.symbols),
                    "types": "forward_split,reverse_split",
                    "start": start,
                    "end": end or datetime.now(UTC).date().isoformat(),
                },
                ctx.acquire,
            )
            payloads.append(actions)
            split = sorted(split_symbols(actions.content) & set(self.symbols))
            payloads += self._pages(client, ctx, bars_params(self.symbols, "raw", start, end))
            payloads += self._pages(client, ctx, bars_params(self.symbols, "split", start, end))
            if split and start > BACKFILL_START:
                payloads += self._pages(
                    client, ctx, bars_params(split, "split", BACKFILL_START, end)
                )
        return payloads

    @staticmethod
    def _pages(
        client: AlpacaClient, ctx: FetchContext, params: dict[str, str]
    ) -> list[FetchedPayload]:
        pages = []
        token: str | None = None
        while True:
            page = client.get(
                "/v2/stocks/bars",
                {**params, **({"page_token": token} if token else {})},
                ctx.acquire,
            )
            pages.append(page)
            token = json.loads(page.content).get("next_page_token")
            if not token:
                return pages

    def store(self, ctx: StoreContext) -> StoreResult:
        source = ctx.session.get_one(Source, SOURCE_ID)
        instruments = resolve_instruments(
            ctx.session,
            self.symbols,
            {str(s).upper() for s in self.params.get("etfs", [])},
            at=ctx.payloads[0].fetched_at,
        )
        bars: list[BarIn] = []
        for payload in ctx.payloads:
            adjustment = adjustment_of(payload.source_url)
            if adjustment is None:
                continue
            for symbol, rows in (json.loads(payload.content).get("bars") or {}).items():
                if symbol in instruments:
                    bars += [
                        _bar(symbol, instruments[symbol], adjustment, row, payload, source, ctx)
                        for row in rows
                    ]
        if self.feed_status != "end_of_day":
            bars = [replace(bar, feed_status=self.feed_status) for bar in bars]
        result = PriceRepository(ctx.session).insert_bars(bars, actor=ACTOR)
        return StoreResult(
            inserted=result.inserted, unchanged=result.unchanged, conflicted=len(result.conflicts)
        )


def _bar(
    symbol: str,
    instrument_id: UUID,
    adjustment: str,
    row: dict[str, Any],
    payload: StoredPayload,
    source: Source,
    ctx: StoreContext,
) -> BarIn:
    bar_time = parse_time(row["t"])
    bar_date: date = bar_time.astimezone(_NEW_YORK).date()
    precision: TimePrecision
    if adjustment == "raw":
        published, precision = end_of_day(bar_date), "day"
    else:  # the split-adjusted basis is what we knew when we fetched it
        published, precision = payload.fetched_at, "exact"
    return BarIn(
        instrument_id=instrument_id,
        symbol=symbol,
        adjustment=adjustment,
        bar_time=bar_time,
        open=Decimal(str(row["o"])),
        high=Decimal(str(row["h"])),
        low=Decimal(str(row["l"])),
        close=Decimal(str(row["c"])),
        volume=int(row["v"]),
        vwap=Decimal(str(row["vw"])) if row.get("vw") is not None else None,
        trade_count=row.get("n"),
        feed="sip",
        feed_status="end_of_day",
        provenance=Provenance(
            source_id=source.id,
            source_tier=source.tier,
            source_url=payload.source_url,
            published_at=published,
            published_at_precision=precision,
            ingested_at=payload.fetched_at,
            effective_from=bar_time,
            effective_to=bar_time + timedelta(days=1),
            as_of=bar_time,
            license_status=cast(LicenseStatus, source.license_status),
            confidence=1.0,
            source_timezone="America/New_York",
            ingestion_run_id=ctx.run_id,
            raw_payload_sha256=payload.sha256,
        ),
    )
