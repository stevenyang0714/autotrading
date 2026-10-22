"""Taiwan universe codes -> instruments (M3.7, ADR-039 TW3).

Each code of config/universe_tw.yaml becomes an instrument on the TWSE (primary exchange XTAI,
currency TWD) with a `twse` ticker identifier; a company also gets an issuer entity (country
TW) named as in the company file (公司名稱), or from config/instrument_labels.yaml when that file
was not fetched. Created on the first run; later runs only look them up.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from autotrading.adapters.twse.client import SOURCE_ID
from autotrading.db.models import Entity, Identifier, Instrument
from autotrading.domain.markets import TW
from autotrading.domain.twse import CompanyRow
from autotrading.repositories.identifiers import current_identifier
from autotrading.repositories.labels import label


def existing_instruments(session: Session, codes: Iterable[str]) -> dict[str, UUID]:
    """code -> instrument id of the codes that have a twse identifier already."""
    found: dict[str, UUID] = {}
    for code in codes:
        row = current_identifier(session, "ticker", TW.namespace, code)
        if row is not None and row.instrument_id is not None:
            found[code] = row.instrument_id
    return found


def resolve_instruments(
    session: Session,
    equities: Iterable[str],
    etfs: Iterable[str],
    companies: Mapping[str, CompanyRow],
    *,
    at: datetime,
) -> dict[str, UUID]:
    """code -> instrument id, creating the instruments, entities and identifiers missing."""
    funds = set(etfs)
    codes = [*equities, *funds]
    resolved = existing_instruments(session, codes)
    for code in codes:
        if code in resolved:
            continue
        entity_id = None
        if code not in funds:
            company = companies.get(code)
            entity = Entity(
                name=company.name if company else label(code).name,
                entity_type="company",
                country="TW",
            )
            session.add(entity)
            session.flush()
            entity_id = entity.id
        instrument = Instrument(
            entity_id=entity_id,
            instrument_type="etf" if code in funds else "equity",
            primary_exchange=TW.exchange,
            currency=TW.currency,
        )
        session.add(instrument)
        session.flush()
        session.add(
            Identifier(
                instrument_id=instrument.id,
                id_type="ticker",
                id_namespace=TW.namespace,
                id_value=code,
                valid_from=at,
                source_id=SOURCE_ID,
            )
        )
        session.flush()
        resolved[code] = instrument.id
    return resolved
