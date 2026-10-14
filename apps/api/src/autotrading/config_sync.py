"""Load repo config into the database (run by `make migrate`).

- config/sources.yaml -> Source Registry (M0.3). Upserts by id and only writes rows whose
  values changed, so re-running is a no-op and the audit log stays quiet. Sources missing from
  the file are left untouched and reported.
- config/macro_series.yaml -> macro_series (M0.6); titles and units come from FRED later.
- docs/glossary/glossary_seed.yaml -> glossary_terms (M0.4). Registers new versions of
  complete terms; refuses changed content under an existing methodology_version.
- config/buyback_rules.yaml -> buyback_rule_sets (M1.4b, ADR-025 B4). Registers new rule
  versions; refuses changed content under a released rule_version.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.db.models import (
    AlertRuleSet,
    BuybackRuleSet,
    FactorDefinitionSet,
    GlossaryTermRow,
    MacroSeries,
    RegimeRuleSet,
    Source,
)
from autotrading.domain.buyback_states import RulesFile
from autotrading.domain.convergence import AlertRulesFile
from autotrading.domain.factors import FactorDefinitionsFile
from autotrading.domain.glossary import GlossaryFile
from autotrading.domain.provenance import LicenseStatus
from autotrading.domain.regime import RegimeRulesFile
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


class MacroSeriesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[A-Z0-9_]+$")
    term_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    position: int = Field(ge=0)
    enabled: bool = True
    # Earliest observation read: for series that re-estimate their whole history every week
    # (NFCI, STLFSI4), whose every vintage would otherwise be read daily (M2.1, ADR-029).
    observation_start: date | None = None


class MacroSeriesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    series: list[MacroSeriesConfig]


def load_macro_series(path: Path) -> MacroSeriesFile:
    parsed = MacroSeriesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [series.id for series in parsed.series]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate series ids in {path}")
    return parsed


def sync_macro_series(session: Session, config: MacroSeriesFile) -> SyncResult:
    """config/macro_series.yaml -> macro_series (M0.6). Series missing from the file are
    disabled, not deleted: their observations stay."""
    set_actor(session, "config:macro_series.yaml")
    result = SyncResult()
    for wanted in config.series:
        values = {**wanted.model_dump(exclude={"id"}), "source_id": "fred"}
        row = session.get(MacroSeries, wanted.id)
        if row is None:
            session.add(MacroSeries(id=wanted.id, **values))
            result.created.append(wanted.id)
            continue
        changed = {k: v for k, v in values.items() if getattr(row, k) != v}
        for key, value in changed.items():
            setattr(row, key, value)
        (result.updated if changed else result.unchanged).append(wanted.id)
    configured = {series.id for series in config.series}
    for row in session.scalars(select(MacroSeries).where(MacroSeries.id.not_in(configured))):
        if row.enabled:
            row.enabled = False
        result.not_in_config.append(row.id)
    session.flush()
    return result


class GlossaryVersionError(ValueError):
    """A complete term's content changed without a methodology_version bump."""


@dataclass
class GlossarySyncResult:
    created: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


def load_glossary(path: Path) -> GlossaryFile:
    return GlossaryFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sync_glossary(session: Session, glossary: GlossaryFile) -> GlossarySyncResult:
    result = GlossarySyncResult()
    for term in glossary.complete_terms():
        sha = term.content_sha256()
        existing = session.get(GlossaryTermRow, (term.term_id, term.methodology_version))
        if existing is not None:
            if existing.content_sha256 != sha:
                raise GlossaryVersionError(
                    f"glossary term {term.term_id} changed but methodology_version "
                    f"{term.methodology_version} was not bumped"
                )
            result.unchanged.append(term.term_id)
            continue
        session.add(
            GlossaryTermRow(
                **term.model_dump(exclude={"status"}),
                content_sha256=sha,
            )
        )
        result.created.append(term.term_id)
    session.flush()
    return result


class BuybackRulesVersionError(ValueError):
    """A released rule set's content changed without a new rule_version."""


def load_buyback_rules(path: Path) -> RulesFile:
    return RulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sync_buyback_rules(session: Session, rules: RulesFile) -> GlossarySyncResult:
    """Register each rule_version once; the same version with other content is refused."""
    set_actor(session, "config:buyback_rules.yaml")
    result = GlossarySyncResult()
    for entry in rules.rule_sets:
        rule_set = entry.rule_set()
        sha = rule_set.content_sha256()
        existing = session.scalars(
            select(BuybackRuleSet).where(BuybackRuleSet.rule_version == rule_set.rule_version)
        ).first()
        if existing is not None:
            if existing.content_sha256 != sha:
                raise BuybackRulesVersionError(
                    f"buyback rule set {rule_set.rule_version} changed but its rule_version "
                    "was not bumped"
                )
            result.unchanged.append(rule_set.rule_version)
            continue
        session.add(
            BuybackRuleSet(
                rule_version=rule_set.rule_version,
                content=rule_set.content(),
                content_sha256=sha,
                approved=rule_set.approved,
            )
        )
        result.created.append(rule_set.rule_version)
    session.flush()
    return result


class AlertRulesVersionError(ValueError):
    """A released alert rule set's content changed without a new rule_version."""


def load_alert_rules(path: Path) -> AlertRulesFile:
    return AlertRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sync_alert_rules(session: Session, rules: AlertRulesFile) -> GlossarySyncResult:
    """Register each alert rule_version once; the same version with other content is refused
    (ADR-028, as the buyback rules)."""
    set_actor(session, "config:alert_rules.yaml")
    result = GlossarySyncResult()
    for entry in rules.rule_sets:
        rule_set = entry.rule_set()
        sha = rule_set.content_sha256()
        existing = session.scalars(
            select(AlertRuleSet).where(AlertRuleSet.rule_version == rule_set.rule_version)
        ).first()
        if existing is not None:
            if existing.content_sha256 != sha:
                raise AlertRulesVersionError(
                    f"alert rule set {rule_set.rule_version} changed but its rule_version "
                    "was not bumped"
                )
            result.unchanged.append(rule_set.rule_version)
            continue
        session.add(
            AlertRuleSet(
                rule_version=rule_set.rule_version,
                content=rule_set.content(),
                content_sha256=sha,
                released=rule_set.released,
            )
        )
        result.created.append(rule_set.rule_version)
    session.flush()
    return result


class RegimeRulesVersionError(ValueError):
    """A released regime rule set's content changed without a new rule_version."""


def load_regime_rules(path: Path) -> RegimeRulesFile:
    return RegimeRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sync_regime_rules(session: Session, rules: RegimeRulesFile) -> GlossarySyncResult:
    """Register each regime rule_version once; the same version with other content is refused
    (ADR-029, as the buyback and alert rules)."""
    set_actor(session, "config:regime_rules.yaml")
    result = GlossarySyncResult()
    for entry in rules.rule_sets:
        rule_set = entry.rule_set()
        sha = rule_set.content_sha256()
        existing = session.scalars(
            select(RegimeRuleSet).where(RegimeRuleSet.rule_version == rule_set.rule_version)
        ).first()
        if existing is not None:
            if existing.content_sha256 != sha:
                raise RegimeRulesVersionError(
                    f"regime rule set {rule_set.rule_version} changed but its rule_version "
                    "was not bumped"
                )
            result.unchanged.append(rule_set.rule_version)
            continue
        session.add(
            RegimeRuleSet(
                rule_version=rule_set.rule_version,
                content=rule_set.content(),
                content_sha256=sha,
                released=rule_set.released,
            )
        )
        result.created.append(rule_set.rule_version)
    session.flush()
    return result


class FactorDefinitionsVersionError(ValueError):
    """A released factor definition set's content changed without a new definition_version."""


def load_factor_definitions(path: Path) -> FactorDefinitionsFile:
    return FactorDefinitionsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def sync_factor_definitions(
    session: Session, definitions: FactorDefinitionsFile
) -> GlossarySyncResult:
    """Register each factor definition_version once; the same version with other content is
    refused (ADR-030, as the regime rules)."""
    set_actor(session, "config:factor_definitions.yaml")
    result = GlossarySyncResult()
    for entry in definitions.definition_sets:
        definition_set = entry.definitions()
        sha = definition_set.content_sha256()
        existing = session.scalars(
            select(FactorDefinitionSet).where(
                FactorDefinitionSet.definition_version == definition_set.definition_version
            )
        ).first()
        if existing is not None:
            if existing.content_sha256 != sha:
                raise FactorDefinitionsVersionError(
                    f"factor definition set {definition_set.definition_version} changed but its "
                    "definition_version was not bumped"
                )
            result.unchanged.append(definition_set.definition_version)
            continue
        session.add(
            FactorDefinitionSet(
                definition_version=definition_set.definition_version,
                content=definition_set.content(),
                content_sha256=sha,
                released=definition_set.released,
            )
        )
        result.created.append(definition_set.definition_version)
    session.flush()
    return result


def main() -> None:
    settings = get_settings()
    sources_path = settings.resolved_config_dir() / "sources.yaml"
    macro_path = settings.resolved_config_dir() / "macro_series.yaml"
    glossary_path = settings.resolved_glossary_path()
    engine = make_engine(settings)
    try:
        with Session(engine) as session:
            sources = sync_sources(session, load_sources(sources_path))
            macro = sync_macro_series(session, load_macro_series(macro_path))
            glossary = sync_glossary(session, load_glossary(glossary_path))
            rules = sync_buyback_rules(
                session, load_buyback_rules(settings.resolved_config_dir() / "buyback_rules.yaml")
            )
            regime = sync_regime_rules(
                session, load_regime_rules(settings.resolved_config_dir() / "regime_rules.yaml")
            )
            alerts = sync_alert_rules(
                session, load_alert_rules(settings.resolved_config_dir() / "alert_rules.yaml")
            )
            factors = sync_factor_definitions(
                session,
                load_factor_definitions(settings.resolved_config_dir() / "factor_definitions.yaml"),
            )
            session.commit()
    finally:
        engine.dispose()
    print(
        f"sources.yaml synced: created={sources.created} updated={sources.updated} "
        f"unchanged={len(sources.unchanged)} not_in_config={sources.not_in_config}"
    )
    print(
        f"macro_series.yaml synced: created={macro.created} updated={macro.updated} "
        f"unchanged={len(macro.unchanged)} disabled={macro.not_in_config}"
    )
    print(
        f"glossary synced: new term versions={len(glossary.created)} "
        f"unchanged={len(glossary.unchanged)}"
    )
    print(f"buyback_rules.yaml synced: new rule versions={rules.created}")
    print(f"regime_rules.yaml synced: new rule versions={regime.created}")
    print(f"alert_rules.yaml synced: new rule versions={alerts.created}")
    print(f"factor_definitions.yaml synced: new definition versions={factors.created}")


if __name__ == "__main__":
    main()
