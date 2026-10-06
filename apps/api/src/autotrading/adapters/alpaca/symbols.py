"""Universe symbols -> instruments for Alpaca (M0.7).

Equities already exist (sec.tickers, M0.5): they get an `alpaca` ticker identifier pointing at
the same instrument. ETFs from config/universe.yaml become instruments of type etf. Alpaca
spells share classes with a dot (BRK.B); the namespace keeps that apart from SEC (BRK-B).
"""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from autotrading.db.models import Identifier, Instrument
from autotrading.repositories.identifiers import current_identifier

logger = logging.getLogger(__name__)

SOURCE_ID = "alpaca_iex"
NAMESPACE = "alpaca"


def resolve_instruments(
    session: Session, symbols: list[str], etfs: set[str], *, at: datetime
) -> dict[str, UUID]:
    """symbol -> instrument id, creating ETF instruments and alpaca identifiers as needed.
    Equities without an SEC instrument yet (sec.tickers not run) are skipped and logged."""
    resolved: dict[str, UUID] = {}
    for symbol in symbols:
        existing = current_identifier(session, "ticker", NAMESPACE, symbol)
        if existing is not None and existing.instrument_id is not None:
            resolved[symbol] = existing.instrument_id
            continue
        if symbol in etfs:
            instrument = Instrument(instrument_type="etf", currency="USD")
            session.add(instrument)
            session.flush()
            instrument_id = instrument.id
        else:
            sec = current_identifier(session, "ticker", "sec", symbol)
            if sec is None or sec.instrument_id is None:
                logger.warning("%s has no instrument yet (run make sec-refresh); skipped", symbol)
                continue
            instrument_id = sec.instrument_id
        session.add(
            Identifier(
                instrument_id=instrument_id,
                id_type="ticker",
                id_namespace=NAMESPACE,
                id_value=symbol,
                valid_from=at,
                source_id=SOURCE_ID,
            )
        )
        session.flush()
        resolved[symbol] = instrument_id
    return resolved
