"""Job `alpaca.snapshots` (M0.7): latest IEX trade, quote and day bar for every universe
symbol in one request; stored as MarketPriceObservations (errata E1) in market_quotes.

Runs every minute during the US session (ADR-017). A snapshot whose trade and quote times did
not change since the last one is not stored again.
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, cast

from autotrading.adapters.alpaca.client import AlpacaClient
from autotrading.adapters.alpaca.symbols import SOURCE_ID, resolve_instruments
from autotrading.db.models import Source
from autotrading.domain.prices import FeedStatus
from autotrading.domain.provenance import LicenseStatus, Provenance
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.repositories.prices import PriceRepository

ACTOR = f"ingest:{SOURCE_ID}"
VENUE = "IEX"


def parse_time(value: str) -> datetime:
    """Alpaca's RFC 3339 UTC times, with or without (nanosecond) fractions; Python keeps
    microseconds."""
    head, _, fraction = value.rstrip("Z").partition(".")
    return datetime.fromisoformat(f"{head}.{(fraction or '0')[:6]}+00:00")


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@register_job
class AlpacaSnapshotsJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "alpaca.snapshots"
    # What a quote from this job is labelled; recorded fixtures override it with "fixture".
    feed_status: ClassVar[FeedStatus] = "live_single_venue"

    def client(self) -> AlpacaClient:
        return AlpacaClient.from_settings()

    @property
    def symbols(self) -> list[str]:
        return [str(s).upper() for s in self.params["symbols"]]

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        with self.client() as client:
            params = {"symbols": ",".join(self.symbols), "feed": "iex"}
            return [client.get("/v2/stocks/snapshots", params, ctx.acquire)]

    def store(self, ctx: StoreContext) -> StoreResult:
        (payload,) = ctx.payloads
        data: dict[str, Any] = json.loads(payload.content)
        source = ctx.session.get_one(Source, SOURCE_ID)
        instruments = resolve_instruments(
            ctx.session,
            self.symbols,
            {str(s).upper() for s in self.params.get("etfs", [])},
            at=payload.fetched_at,
        )
        rows = []
        for symbol, snapshot in data.items():
            if symbol not in instruments or not snapshot:
                continue
            trade, quote = snapshot.get("latestTrade") or {}, snapshot.get("latestQuote") or {}
            day, prev = snapshot.get("dailyBar") or {}, snapshot.get("prevDailyBar") or {}
            times = [parse_time(t) for t in (trade.get("t"), quote.get("t")) if t]
            if not times:
                continue
            published = max(times)
            provenance = Provenance(
                source_id=source.id,
                source_tier=source.tier,
                source_url=payload.source_url,
                published_at=published,
                published_at_precision="exact",
                ingested_at=payload.fetched_at,
                effective_from=published,
                as_of=published,
                license_status=cast(LicenseStatus, source.license_status),
                confidence=1.0,
                source_timezone="America/New_York",
                ingestion_run_id=ctx.run_id,
                raw_payload_sha256=payload.sha256,
            )
            rows.append(
                {
                    "instrument_id": instruments[symbol],
                    "symbol": symbol,
                    "venue": VENUE,
                    "bid": _decimal(quote.get("bp")),
                    "ask": _decimal(quote.get("ap")),
                    "bid_size": quote.get("bs"),
                    "ask_size": quote.get("as"),
                    "last": _decimal(trade.get("p")),
                    "last_size": trade.get("s"),
                    "day_open": _decimal(day.get("o")),
                    "day_high": _decimal(day.get("h")),
                    "day_low": _decimal(day.get("l")),
                    "day_volume": day.get("v"),
                    "prev_close": _decimal(prev.get("c")),
                    "currency": "USD",
                    "received_at": payload.fetched_at,
                    "feed_status": self.feed_status,
                    "adjustment_status": "raw",
                    **provenance.model_dump(),
                }
            )
        inserted = PriceRepository(ctx.session).insert_quotes(rows, actor=ACTOR)
        return StoreResult(inserted=inserted, unchanged=len(rows) - inserted)
