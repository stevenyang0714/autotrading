"""Job `alpaca.splits` (M1.1, ADR-021): stock splits of the universe equities.

fetch: Alpaca corporate actions (forward and reverse splits) since 2016, paged.
store: one split_events row per instrument and ex-date, plus the reviewed earlier splits of
config/splits.yaml (Alpaca's history starts in 2016; each entry cites the issuer's 8-K). A row
already stored is left alone; a different ratio for a stored ex-date is counted as a conflict.
Splits are effective from the start of the ex-date in New York (domain/splits.effective_at).
Runs daily after the daily bars.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.alpaca.client import AlpacaClient
from autotrading.adapters.alpaca.symbols import NAMESPACE, SOURCE_ID
from autotrading.db.models import Source, SplitEvent
from autotrading.domain.provenance import LicenseStatus
from autotrading.domain.splits import effective_at
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoredPayload,
    StoreResult,
    register_job,
)
from autotrading.repositories.identifiers import current_identifier
from autotrading.settings import get_settings

HISTORY_START = "2016-01-01"
KINDS = {"forward_splits": "forward_split", "reverse_splits": "reverse_split"}
CURATED_SOURCE = "sec_edgar"


class CuratedSplit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    ex_date: date
    old_rate: Decimal = Field(gt=0)
    new_rate: Decimal = Field(gt=0)
    kind: str = Field(pattern="^(forward_split|reverse_split|stock_dividend)$")
    source_url: str = Field(pattern=r"^https://www\.sec\.gov/Archives/")
    evidence: str


def load_curated(config_dir: Path) -> list[CuratedSplit]:
    data = yaml.safe_load((config_dir / "splits.yaml").read_text(encoding="utf-8"))
    return [CuratedSplit.model_validate(item) for item in data.get("splits") or []]


def _instrument(session: Session, symbol: str) -> Any:
    for namespace in (NAMESPACE, "sec"):
        identifier = current_identifier(session, "ticker", namespace, symbol)
        if identifier is not None and identifier.instrument_id is not None:
            return identifier.instrument_id
    return None


@register_job
class AlpacaSplitsJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "alpaca.splits"

    def client(self) -> AlpacaClient:
        return AlpacaClient.from_settings()

    def config_dir(self) -> Path:
        return get_settings().resolved_config_dir()

    @property
    def symbols(self) -> list[str]:
        return [str(s).upper() for s in self.params["symbols"]]

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        params = {
            "symbols": ",".join(self.symbols),
            "types": "forward_split,reverse_split",
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
        rows: list[dict[str, Any]] = []
        for payload in ctx.payloads:
            actions = json.loads(payload.content).get("corporate_actions") or {}
            for key, kind in KINDS.items():
                for action in actions.get(key) or []:
                    rows.append(self._alpaca_row(session, action, kind, payload, ctx))
        rows += [
            self._curated_row(session, split, ctx) for split in load_curated(self.config_dir())
        ]
        return _insert(session, [row for row in rows if row])

    def _alpaca_row(
        self,
        session: Session,
        action: dict[str, Any],
        kind: str,
        payload: StoredPayload,
        ctx: StoreContext,
    ) -> dict[str, Any]:
        symbol = str(action["symbol"]).upper()
        instrument_id = _instrument(session, symbol)
        if instrument_id is None:
            return {}
        source = session.get_one(Source, SOURCE_ID)
        return _row(
            instrument_id=instrument_id,
            symbol=symbol,
            ex_date=date.fromisoformat(action["ex_date"]),
            old_rate=Decimal(str(action["old_rate"])),
            new_rate=Decimal(str(action["new_rate"])),
            kind=kind,
            source=source,
            source_url=payload.source_url,
            ingested_at=payload.fetched_at,
            run_id=ctx.run_id,
            sha256=payload.sha256,
        )

    def _curated_row(
        self, session: Session, split: CuratedSplit, ctx: StoreContext
    ) -> dict[str, Any]:
        instrument_id = _instrument(session, split.ticker)
        if instrument_id is None:
            return {}
        return _row(
            instrument_id=instrument_id,
            symbol=split.ticker,
            ex_date=split.ex_date,
            old_rate=split.old_rate,
            new_rate=split.new_rate,
            kind=split.kind,
            source=session.get_one(Source, CURATED_SOURCE),
            source_url=split.source_url,
            ingested_at=ctx.payloads[0].fetched_at if ctx.payloads else datetime.now(UTC),
            run_id=ctx.run_id,
            sha256=None,
        )


def _row(
    *,
    instrument_id: Any,
    symbol: str,
    ex_date: date,
    old_rate: Decimal,
    new_rate: Decimal,
    kind: str,
    source: Source,
    source_url: str,
    ingested_at: datetime,
    run_id: Any,
    sha256: str | None,
) -> dict[str, Any]:
    effective = effective_at(ex_date)
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "ex_date": ex_date,
        "old_rate": old_rate,
        "new_rate": new_rate,
        "kind": kind,
        "source_id": source.id,
        "source_tier": source.tier,
        "source_url": source_url,
        "published_at": effective,
        "published_at_precision": "day",
        "ingested_at": ingested_at,
        "effective_from": effective,
        "effective_to": None,
        "as_of": effective,
        "license_status": cast(LicenseStatus, source.license_status),
        "confidence": Decimal(1),
        "source_timezone": "America/New_York",
        "ingestion_run_id": run_id,
        "raw_payload_sha256": sha256,
    }


def _insert(session: Session, rows: list[dict[str, Any]]) -> StoreResult:
    """New ex-dates are inserted; a stored ex-date with the same ratio is unchanged, with
    another ratio a conflict (the stored row stays)."""
    stored = {
        (s.instrument_id, s.ex_date): (s.old_rate, s.new_rate)
        for s in session.scalars(select(SplitEvent))
    }
    inserted = unchanged = conflicted = 0
    seen: set[tuple[Any, date]] = set()
    for row in rows:
        key = (row["instrument_id"], row["ex_date"])
        if key in seen:
            continue
        seen.add(key)
        if key in stored:
            old, new = stored[key]
            if Decimal(new) / Decimal(old) == row["new_rate"] / row["old_rate"]:
                unchanged += 1
            else:
                conflicted += 1
            continue
        session.add(SplitEvent(**row))
        inserted += 1
    session.flush()
    return StoreResult(inserted=inserted, unchanged=unchanged, conflicted=conflicted)
