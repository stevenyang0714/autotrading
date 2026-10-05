"""Load config/sources.yaml into the Source Registry (M0.3).

Run with `python -m autotrading.config_sync` (part of `make migrate`). Upserts by id and only
writes rows whose values changed, so re-running is a no-op and the audit log stays quiet.
Sources missing from the file are left untouched and reported.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.db.models import Source
from autotrading.domain.provenance import LicenseStatus
from autotrading.infra.db import make_engine
from autotrading.repositories.audit import set_actor
from autotrading.settings import get_settings

SYNC_ACTOR = "config:sources.yaml"

AccessStatus = Literal["active", "no_credentials", "disabled", "pending_review"]
UpdateCadence = Literal["intraday", "daily", "weekly", "monthly", "per_filing", "per_release"]


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    tier: int = Field(ge=1, le=4)
    license_status: LicenseStatus
    access_status: AccessStatus
    update_cadence: UpdateCadence
    freshness_sla_seconds: int = Field(gt=0)
    enabled: bool
    priority: int = Field(ge=0)
    topics: list[str]
    rate_limit_per_second: Decimal = Field(gt=0)
    rate_limit_burst: int = Field(ge=1)
    note: str | None = None  # documentation only, not stored


class SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    sources: list[SourceConfig]


@dataclass
class SyncResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    not_in_config: list[str] = field(default_factory=list)


def load_sources(path: Path) -> SourcesFile:
    parsed = SourcesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [source.id for source in parsed.sources]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate source ids in {path}")
    return parsed


def sync_sources(session: Session, config: SourcesFile) -> SyncResult:
    set_actor(session, SYNC_ACTOR)
    result = SyncResult()
    for wanted in config.sources:
        values = wanted.model_dump(exclude={"id", "note"})
        row = session.get(Source, wanted.id)
        if row is None:
            session.add(Source(id=wanted.id, **values))
            result.created.append(wanted.id)
            continue
        changed = {k: v for k, v in values.items() if getattr(row, k) != v}
        if changed:
            for key, value in changed.items():
                setattr(row, key, value)
            result.updated.append(wanted.id)
        else:
            result.unchanged.append(wanted.id)
    configured = {source.id for source in config.sources}
    result.not_in_config = sorted(set(session.scalars(select(Source.id))) - configured)
    session.flush()
    return result


def main() -> None:
    settings = get_settings()
    path = settings.resolved_config_dir() / "sources.yaml"
    engine = make_engine(settings)
    try:
        with Session(engine) as session:
            result = sync_sources(session, load_sources(path))
            session.commit()
    finally:
        engine.dispose()
    print(
        f"sources.yaml synced: created={result.created} updated={result.updated} "
        f"unchanged={len(result.unchanged)} not_in_config={result.not_in_config}"
    )


if __name__ == "__main__":
    main()
