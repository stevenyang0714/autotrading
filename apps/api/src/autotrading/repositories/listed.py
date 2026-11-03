"""The TWSE company file as observed (M3.11, ADR-042 SC1, SC2): listed_companies.

- record_listed: one row per company and change (code, short name, industry, listing date);
  a company the file stops naming gets a row with `listed` false.
- listed_at: the companies the file listed as known at T and held at S.
- known_codes: every code ever recorded; the TWSE run fetches the company file again when a
  four-digit code of STOCK_DAY_ALL is not among them (a new listing).
- industry_names: config/twse_industries.yaml, for display only.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from autotrading.db.models import ListedCompany, Source
from autotrading.domain.markets import TW
from autotrading.domain.provenance import end_of_day
from autotrading.domain.twse import CompanyRow
from autotrading.ingestion.job import StoredPayload
from autotrading.repositories.audit import set_actor
from autotrading.settings import get_settings

ZONE = "Asia/Taipei"


@dataclass(frozen=True)
class Listed:
    instrument_id: UUID
    code: str
    short_name: str
    industry: str
    listed_on: date | None
    row_id: UUID
    published_at: datetime


def _values(row: ListedCompany | CompanyRow, listed: bool) -> tuple[object, ...]:
    return (row.code, row.short_name, row.industry, row.listed_on, listed)


def _latest(
    session: Session, *, known_at: datetime | None = None, system_time: datetime | None = None
) -> list[ListedCompany]:
    """Each company's latest row as known at `known_at` and held at `system_time` (None: now)."""
    query = select(ListedCompany).ext(distinct_on(ListedCompany.instrument_id))
    if known_at is not None:
        query = query.where(ListedCompany.published_at <= known_at)
    if system_time is not None:
        query = query.where(ListedCompany.recorded_at <= system_time)
    query = query.order_by(
        ListedCompany.instrument_id,
        ListedCompany.published_at.desc(),
        ListedCompany.recorded_at.desc(),
    )
    return list(session.scalars(query))


def listed_at(
    session: Session, known_at: datetime | None = None, system_time: datetime | None = None
) -> dict[str, Listed]:
    """code -> the company, for the companies the file listed as known at T and held at S."""
    return {
        row.code: Listed(
            instrument_id=row.instrument_id,
            code=row.code,
            short_name=row.short_name,
            industry=row.industry,
            listed_on=row.listed_on,
            row_id=row.id,
            published_at=row.published_at,
        )
        for row in _latest(session, known_at=known_at, system_time=system_time)
        if row.listed
    }


def known_codes(session: Session) -> set[str]:
    return set(session.scalars(select(ListedCompany.code).distinct()))


def record_listed(
    session: Session,
    companies: Mapping[str, CompanyRow],
    ids: Mapping[str, UUID],
    payload: StoredPayload,
    source: Source,
    run_id: UUID,
    *,
    actor: str,
) -> tuple[int, int]:
    """Store the company file's changes: (inserted, unchanged). A company the file stops naming
    gets a copy of its latest row with `listed` false."""
    set_actor(session, actor)
    as_of = max(c.as_of for c in companies.values())
    start = datetime.combine(as_of, time(0, 0), TW.zone)
    provenance = {
        "source_id": source.id,
        "source_tier": source.tier,
        "source_url": payload.source_url,
        "published_at": min(end_of_day(as_of, ZONE), payload.fetched_at),
        "published_at_precision": "day",
        "ingested_at": payload.fetched_at,
        "effective_from": start,
        "effective_to": None,
        "as_of": start,
        "license_status": source.license_status,
        "confidence": 1,
        "source_timezone": ZONE,
        "ingestion_run_id": run_id,
        "raw_payload_sha256": payload.sha256,
    }
    latest = {row.code: row for row in _latest(session)}
    rows: list[ListedCompany] = []
    unchanged = 0
    for code, company in companies.items():
        stored = latest.get(code)
        if stored is not None and _values(stored, stored.listed) == _values(company, True):
            unchanged += 1
            continue
        rows.append(
            ListedCompany(
                instrument_id=ids[code],
                code=code,
                short_name=company.short_name,
                industry=company.industry,
                listed_on=company.listed_on,
                listed=True,
                **provenance,
            )
        )
    for code, stored in latest.items():
        if code not in companies and stored.listed:
            rows.append(
                ListedCompany(
                    instrument_id=stored.instrument_id,
                    code=code,
                    short_name=stored.short_name,
                    industry=stored.industry,
                    listed_on=stored.listed_on,
                    listed=False,
                    **provenance,
                )
            )
    session.add_all(rows)
    session.flush()
    return len(rows), unchanged


class _IndustriesFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    reviewed: date
    sources: list[str]
    industries: dict[str, str]


@lru_cache
def _industries(path: Path) -> dict[str, str]:
    parsed = _IndustriesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return dict(parsed.industries)


def industry_names(config_dir: Path | None = None) -> dict[str, str]:
    """TWSE industry code -> name (config/twse_industries.yaml)."""
    folder = config_dir or get_settings().resolved_config_dir()
    return _industries(folder / "twse_industries.yaml")
