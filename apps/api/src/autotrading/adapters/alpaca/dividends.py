"""Job `alpaca.dividends` (M2.2, ADR-030): cash dividends of the universe equities and ETFs.

fetch: Alpaca corporate actions (cash dividends) since 2016, paged.
store: one dividend_events row per instrument, ex-date and kind (regular or special). A row
already stored is left alone: the same amount again is unchanged (Alpaca repeats some payments),
another amount is counted as a conflict. Dividends are known from the start of the ex-date in
New York (Alpaca gives no declaration date). Runs daily after the daily bars, with the splits.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.alpaca.client import AlpacaClient
from autotrading.adapters.alpaca.splits import HISTORY_START, instrument_of
from autotrading.adapters.alpaca.symbols import SOURCE_ID
from autotrading.db.models import DividendEvent, Source
from autotrading.domain.provenance import LicenseStatus
from autotrading.domain.splits import effective_at
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value else None


@register_job
class AlpacaDividendsJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "alpaca.dividends"

    def client(self) -> AlpacaClient:
        return AlpacaClient.from_settings()

    @property
    def symbols(self) -> list[str]:
        return [str(s).upper() for s in self.params["symbols"]]

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        params = {
            "symbols": ",".join(self.symbols),
            "types": "cash_dividend",
            "start": str(self.params.get("start", HISTORY_START)),
            "end": str(self.params.get("end") or datetime.now(UTC).date().isoformat()),
            "limit": "1000",
        }
        pages: list[FetchedPayload] = []
        token: str | None = None
        with self.client() as client:
            while True:
                page = client.get(
                    "/v1/corporate-actions",
                    {**params, **({"page_token": token} if token else {})},
                    ctx.acquire,
                )
                pages.append(page)
                token = json.loads(page.content).get("next_page_token")
                if not token:
                    return pages

    def store(self, ctx: StoreContext) -> StoreResult:
        session = ctx.session
        source = session.get_one(Source, SOURCE_ID)
        rows: list[dict[str, Any]] = []
        for payload in ctx.payloads:
            actions = json.loads(payload.content).get("corporate_actions") or {}
            for action in actions.get("cash_dividends") or []:
                symbol = str(action["symbol"]).upper()
                instrument_id = instrument_of(session, symbol)
                if instrument_id is None:
                    continue
                effective = effective_at(date.fromisoformat(action["ex_date"]))
                rows.append(
                    {
                        "instrument_id": instrument_id,
                        "symbol": symbol,
                        "ex_date": date.fromisoformat(action["ex_date"]),
                        "rate": Decimal(str(action["rate"])),
                        "special": bool(action.get("special")),
                        "foreign": bool(action.get("foreign")),
                        "record_date": _day(action.get("record_date")),
                        "payable_date": _day(action.get("payable_date")),
                        "corporate_action_id": action.get("id"),
                        "source_id": source.id,
                        "source_tier": source.tier,
                        "source_url": payload.source_url,
                        "published_at": effective,
                        "published_at_precision": "day",
                        "ingested_at": payload.fetched_at,
                        "effective_from": effective,
                        "effective_to": None,
                        "as_of": effective,
                        "license_status": cast(LicenseStatus, source.license_status),
                        "confidence": Decimal(1),
                        "source_timezone": "America/New_York",
                        "ingestion_run_id": ctx.run_id,
                        "raw_payload_sha256": payload.sha256,
                    }
                )
        return _insert(session, rows)


def _insert(session: Session, rows: list[dict[str, Any]]) -> StoreResult:
    stored = {
        (d.instrument_id, d.ex_date, d.special): d.rate
        for d in session.scalars(select(DividendEvent))
    }
    inserted = unchanged = conflicted = 0
    seen: dict[tuple[Any, date, bool], Decimal] = {}
    for row in rows:
        key = (row["instrument_id"], row["ex_date"], row["special"])
        earlier = stored.get(key, seen.get(key))
        if earlier is not None:
            if Decimal(earlier) == row["rate"]:
                unchanged += 1
            else:
                conflicted += 1
            continue
        seen[key] = row["rate"]
        session.add(DividendEvent(**row))
        inserted += 1
    session.flush()
    return StoreResult(inserted=inserted, unchanged=unchanged, conflicted=conflicted)
