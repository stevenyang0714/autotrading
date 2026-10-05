"""Job `sec.tickers`: ticker <-> CIK map for the universe equities (M0.5).

Reads SEC's company_tickers_exchange.json and keeps, per universe ticker:
- an entity with its CIK identifier (namespace `sec`);
- an equity instrument with its ticker identifier (namespace `sec`) and primary exchange.

Identifiers carry validity periods. valid_from is when this platform first saw the mapping,
not when it began at SEC (the file has no history). A ticker that moves to another CIK closes
its old period; a company whose old ticker vanished from the file keeps its instrument and
gets the new ticker (a rename such as FB -> META).
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.parsing import filing_index_url, normalize_cik
from autotrading.db.models import Entity, EntityRelationship, Identifier, Instrument
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.repositories.identifiers import (
    close_identifier,
    current_identifier,
    current_identifier_of,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "sec_edgar"
NAMESPACE = "sec"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
# SEC exchange names -> ISO 10383 MIC. Others (OTC, CBOE) stay unknown.
EXCHANGE_MIC = {"Nasdaq": "XNAS", "NYSE": "XNYS"}


class Predecessor(BaseModel):
    """An earlier issuer of a universe equity (config/universe.yaml `predecessors:`, ADR-014)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    name: str = Field(min_length=1)
    relationship: Literal["successor_issuer"] = "successor_issuer"
    effective_at: AwareDatetime  # when the successor took over (8-K12B acceptance)
    evidence_accession: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")


@dataclass(frozen=True)
class ListedTicker:
    cik: str
    name: str
    ticker: str
    exchange: str | None


def parse_tickers(content: bytes) -> list[ListedTicker]:
    data: dict[str, Any] = json.loads(content)
    columns = {name: i for i, name in enumerate(data["fields"])}
    return [
        ListedTicker(
            cik=normalize_cik(row[columns["cik"]]),
            name=row[columns["name"]],
            ticker=row[columns["ticker"]],
            exchange=row[columns["exchange"]] or None,
        )
        for row in data["data"]
    ]


@register_job
class SecTickersJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "sec.tickers"

    def client(self) -> SecClient:
        return SecClient.from_settings()

    @property
    def tickers(self) -> list[str]:
        return [str(t).upper() for t in self.params["tickers"]]

    @property
    def predecessors(self) -> dict[str, list[Predecessor]]:
        raw: dict[str, list[dict[str, Any]]] = self.params.get("predecessors") or {}
        return {
            ticker.upper(): [Predecessor.model_validate(item) for item in items]
            for ticker, items in raw.items()
        }

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        with self.client() as client:
            return [client.get(TICKERS_URL, ctx.acquire)]

    def store(self, ctx: StoreContext) -> StoreResult:
        (payload,) = ctx.payloads
        listed = parse_tickers(payload.content)
        by_ticker = {entry.ticker: entry for entry in listed}
        tickers_of_cik: dict[str, set[str]] = defaultdict(set)
        for entry in listed:
            tickers_of_cik[entry.cik].add(entry.ticker)

        inserted = unchanged = 0
        for ticker in self.tickers:
            row = by_ticker.get(ticker)
            if row is None:
                logger.warning("universe ticker %s is not in SEC's ticker file; skipped", ticker)
                continue
            changes = _sync_ticker(ctx.session, row, tickers_of_cik[row.cik], at=payload.fetched_at)
            inserted += changes
            unchanged += changes == 0
        for ticker, predecessors in self.predecessors.items():
            row = by_ticker.get(ticker)
            if row is None or ticker not in self.tickers:
                logger.warning("predecessors of %s skipped: not a listed universe ticker", ticker)
                continue
            for predecessor in predecessors:
                changes = _sync_predecessor(ctx.session, row, predecessor, at=payload.fetched_at)
                inserted += changes
                unchanged += changes == 0
        return StoreResult(inserted=inserted, unchanged=unchanged)


def _sync_ticker(
    session: Session, row: ListedTicker, cik_tickers: set[str], *, at: datetime
) -> int:
    """Bring one ticker's entity, instrument and identifiers in line; returns rows written."""
    written = 0
    cik_id = current_identifier(session, "cik", NAMESPACE, row.cik)
    if cik_id is None or cik_id.entity_id is None:
        entity = Entity(name=row.name, entity_type="company")
        session.add(entity)
        session.flush()
        session.add(_identifier("cik", row.cik, at, entity_id=entity.id))
        written += 2
    else:
        entity = session.get_one(Entity, cik_id.entity_id)
        if entity.name != row.name:
            entity.name = row.name
            written += 1

    mic = EXCHANGE_MIC.get(row.exchange or "")
    ticker_id = current_identifier(session, "ticker", NAMESPACE, row.ticker)
    if ticker_id is not None and ticker_id.instrument_id is not None:
        listed = session.get_one(Instrument, ticker_id.instrument_id)
        if listed.entity_id == entity.id:
            if listed.primary_exchange != mic:
                listed.primary_exchange = mic
                written += 1
            return written
        close_identifier(ticker_id, at)  # the ticker now belongs to another company
        session.flush()
        written += 1

    instrument = _renamed_instrument(session, entity, cik_tickers, at)
    if instrument is None:
        instrument = Instrument(
            entity_id=entity.id, instrument_type="equity", primary_exchange=mic, currency="USD"
        )
        session.add(instrument)
        written += 1
    session.flush()
    session.add(_identifier("ticker", row.ticker, at, instrument_id=instrument.id))
    return written + 1


def _sync_predecessor(
    session: Session, successor: ListedTicker, predecessor: Predecessor, *, at: datetime
) -> int:
    """Ensure the predecessor entity, its CIK and the link to the ticker's current issuer."""
    successor_id = current_identifier(session, "cik", NAMESPACE, successor.cik)
    if successor_id is None or successor_id.entity_id is None:
        raise LookupError(f"no entity for CIK {successor.cik}")  # _sync_ticker runs first
    written = 0
    cik_id = current_identifier(session, "cik", NAMESPACE, predecessor.cik)
    if cik_id is None or cik_id.entity_id is None:
        entity = Entity(name=predecessor.name, entity_type="company")
        session.add(entity)
        session.flush()
        session.add(_identifier("cik", predecessor.cik, at, entity_id=entity.id))
        predecessor_entity_id = entity.id
        written += 2
    else:
        predecessor_entity_id = cik_id.entity_id

    wanted = {
        "effective_at": predecessor.effective_at,
        "evidence_accession": predecessor.evidence_accession,
        "evidence_url": filing_index_url(successor.cik, predecessor.evidence_accession),
    }
    link = session.scalars(
        select(EntityRelationship).where(
            EntityRelationship.predecessor_entity_id == predecessor_entity_id,
            EntityRelationship.successor_entity_id == successor_id.entity_id,
            EntityRelationship.relationship_type == predecessor.relationship,
        )
    ).first()
    if link is None:
        session.add(
            EntityRelationship(
                predecessor_entity_id=predecessor_entity_id,
                successor_entity_id=successor_id.entity_id,
                relationship_type=predecessor.relationship,
                source_id=SOURCE_ID,
                **wanted,
            )
        )
        session.flush()
        return written + 1
    changed = {k: v for k, v in wanted.items() if getattr(link, k) != v}
    for key, value in changed.items():
        setattr(link, key, value)
    return written + bool(changed)


def _renamed_instrument(
    session: Session, entity: Entity, cik_tickers: set[str], at: datetime
) -> Instrument | None:
    """An equity of this entity whose current SEC ticker is no longer listed for the CIK."""
    equities = session.scalars(
        select(Instrument).where(
            Instrument.entity_id == entity.id, Instrument.instrument_type == "equity"
        )
    ).all()
    for instrument in equities:
        old = current_identifier_of(session, "ticker", NAMESPACE, instrument_id=instrument.id)
        if old is not None and old.id_value not in cik_tickers:
            close_identifier(old, at)
            session.flush()
            return instrument
    return None


def _identifier(id_type: str, value: str, at: datetime, **subject: Any) -> Identifier:
    return Identifier(
        id_type=id_type,
        id_namespace=NAMESPACE,
        id_value=value,
        valid_from=at,
        source_id=SOURCE_ID,
        **subject,
    )
