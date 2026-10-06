"""News configuration (ADR-018): config/news_feeds.yaml, news_publishers.yaml and
news_entities.yaml, plus the company dictionary built from them and the SEC names."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.db.models import Entity, Identifier, Instrument
from autotrading.domain.news import Company, PublisherTiers, company_names
from autotrading.settings import get_settings


class FeedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    url: str = Field(pattern=r"^https://")
    publisher: str = Field(min_length=1)
    kind: Literal["official", "press_release"]
    ticker: str | None = Field(default=None, pattern=r"^[A-Z.]+$")


class FeedsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    feeds: list[FeedConfig]


class PublisherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: int = Field(ge=1, le=4)
    name: str = Field(min_length=1)


class PublishersFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    default_tier: int = Field(ge=1, le=4)
    official_suffixes: list[str]
    publishers: dict[str, PublisherConfig]
    blocked: list[str] = Field(default_factory=list)

    def tiers(self) -> PublisherTiers:
        return PublisherTiers(
            publishers={d: (p.tier, p.name) for d, p in self.publishers.items()},
            official_suffixes=tuple(self.official_suffixes),
            default_tier=self.default_tier,
            blocked=frozenset(d.lower() for d in self.blocked),
        )


class CompanyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aliases: list[str] = Field(min_length=1)
    gdelt_query: str = Field(min_length=3)
    bare_ticker: bool = True


class EntitiesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    companies: dict[str, CompanyConfig]


def _load(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_feeds(config_dir: Path) -> FeedsFile:
    parsed = FeedsFile.model_validate(_load(config_dir / "news_feeds.yaml"))
    ids = [feed.source_id for feed in parsed.feeds]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source ids in news_feeds.yaml")
    return parsed


def load_publishers(config_dir: Path) -> PublishersFile:
    return PublishersFile.model_validate(_load(config_dir / "news_publishers.yaml"))


def load_entities(config_dir: Path) -> EntitiesFile:
    return EntitiesFile.model_validate(_load(config_dir / "news_entities.yaml"))


@lru_cache
def feeds() -> dict[str, FeedConfig]:
    """Configured feeds by source id, read once per process."""
    return {f.source_id: f for f in load_feeds(get_settings().resolved_config_dir()).feeds}


@lru_cache
def publisher_tiers() -> PublisherTiers:
    return load_publishers(get_settings().resolved_config_dir()).tiers()


@lru_cache
def entities() -> EntitiesFile:
    return load_entities(get_settings().resolved_config_dir())


def universe_companies(session: Session) -> dict[str, tuple[Company, UUID]]:
    """ticker -> (Company to match, instrument id) for configured companies that exist as
    instruments (sec.tickers has run). Names: configured aliases plus the SEC name."""
    configured = entities().companies
    rows = session.execute(
        select(Identifier.id_value, Instrument.id, Entity.name)
        .join(Instrument, Instrument.id == Identifier.instrument_id)
        .join(Entity, Entity.id == Instrument.entity_id, isouter=True)
        .where(
            Identifier.id_type == "ticker",
            Identifier.id_namespace == "sec",
            Identifier.valid_to.is_(None),
            Identifier.id_value.in_(list(configured)),
        )
    ).all()
    companies: dict[str, tuple[Company, UUID]] = {}
    for ticker, instrument_id, sec_name in rows:
        settings = configured[ticker]
        companies[ticker] = (
            Company(ticker, company_names(sec_name, settings.aliases), settings.bare_ticker),
            instrument_id,
        )
    return companies
