"""Regime assessments (M2.1, ADR-029): the macro observations and closes known at (T, S), the
stored assessment, and the market-wide alert when the stress state changes, in the caller's
transaction.

Every input is read as known at T and as this database held it at S (macro vintages through
`as_of_query`, closes through `daily_bars`), so a stored assessment recomputes identically.
One assessment per T and rule version; re-running is harmless.
"""

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from autotrading.db.models import MacroObservation, RegimeAssessment
from autotrading.db.models import RegimeRuleSet as RegimeRuleSetRow
from autotrading.domain.convergence import AlertIn
from autotrading.domain.regime import (
    STRESS_ORDER,
    Bar,
    Obs,
    Regime,
    RegimeRuleSet,
    RegimeRulesFile,
    assess,
)
from autotrading.repositories.audit import set_actor
from autotrading.repositories.convergence import insert_alert, stored_alert_rules
from autotrading.repositories.facts import as_of_query
from autotrading.repositories.prices import daily_bars, instruments_by_symbol
from autotrading.settings import get_settings

ACTOR = "rules:regime_rules"
MONTHLY = timedelta(days=6 * 366)  # Sahm rule (15 months), year on year, a quarter back
# Series -> how far back the assessment reads: enough for every rule, no more.
SERIES: dict[str, timedelta] = {
    "UNRATE": MONTHLY,
    "PAYEMS": MONTHLY,
    "GDPC1": MONTHLY,
    "PCEPILFE": MONTHLY,
    "CPIAUCSL": MONTHLY,
    "FEDFUNDS": MONTHLY,
    "T10Y2Y": timedelta(days=4 * 366),  # the current inversion streak
    "NFCI": timedelta(days=120),
    "NFCICREDIT": timedelta(days=120),
    "STLFSI4": timedelta(days=120),
    "BAMLH0A0HYM2": timedelta(days=120),
    "VIXCLS": timedelta(days=60),
    "VXVCLS": timedelta(days=60),
    "DTWEXBGS": timedelta(days=120),
    "DCOILWTICO": timedelta(days=120),
}
BARS = timedelta(days=400)  # 252 sessions for the drawdown, 60 for the correlation
SYMBOLS = ("SPY", "TLT")


def load_regime_rules(path: Path | None = None) -> RegimeRulesFile:
    path = path or get_settings().resolved_config_dir() / "regime_rules.yaml"
    return RegimeRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _file() -> RegimeRulesFile:
    return load_regime_rules()


def active_regime_version() -> str:
    return _file().active().rule_version


def stored_regime_rules(session: Session, rule_version: str | None = None) -> RegimeRuleSet | None:
    """A released regime rule set as `make migrate` registered it; None when not loaded."""
    version = rule_version or active_regime_version()
    row = session.scalars(
        select(RegimeRuleSetRow).where(RegimeRuleSetRow.rule_version == version)
    ).first()
    return RegimeRuleSet.model_validate(row.content) if row else None


def inputs_at(
    session: Session, at: datetime, system_time: datetime
) -> tuple[dict[str, list[Obs]], list[Bar], list[Bar]]:
    """Each series' observations known at (T, S) over its lookback, and SPY and TLT closes."""
    series: dict[str, list[Obs]] = {}
    for series_id, lookback in SERIES.items():
        known = as_of_query(MacroObservation, known_at=at, system_time=system_time).where(
            MacroObservation.series_id == series_id,
            MacroObservation.observation_date >= (at - lookback).date(),
        )
        row = aliased(MacroObservation, known.subquery())
        series[series_id] = [
            Obs(r.observation_date, r.value, r.vintage)
            for r in session.scalars(select(row).order_by(row.observation_date))
        ]
    symbols = instruments_by_symbol(session, list(SYMBOLS))
    closes = {
        symbol: [
            Bar(b.bar_date, b.close)
            for b in daily_bars(
                session,
                instrument,
                "raw",
                since=at - BARS,
                until=at,
                known_at=at,
                system_time=system_time,
            )
        ]
        if (instrument := symbols.get(symbol))
        else []
        for symbol in SYMBOLS
    }
    return series, closes["SPY"], closes["TLT"]


def regime_at(
    session: Session, rules: RegimeRuleSet, at: datetime, system_time: datetime
) -> Regime:
    series, spy, tlt = inputs_at(session, at, system_time)
    return assess(rules, at, series, spy, tlt)


def _stress_alert(regime: Regime, previous: str, assessment_id: UUID) -> AlertIn:
    assert regime.stress is not None
    now, then = regime.stress.upper(), previous.upper()
    up = STRESS_ORDER[regime.stress] > STRESS_ORDER[previous]
    title = f"Market stress {'rose' if up else 'eased'} to {now} (was {then})"
    basis = {
        "table": "regime_assessments",
        "id": str(assessment_id),
        "label": f"Stress {now}: {regime.stress_detail}",
    }
    flagged = [
        {"table": "regime_assessments", "id": str(assessment_id), "label": f.label}
        for f in regime.flags
        if f.status == "on"
    ]
    return AlertIn(
        kind="regime",
        level=STRESS_ORDER[regime.stress],
        previous_level=STRESS_ORDER[previous],
        direction="up" if up else "down",
        title=title,
        source_key=f"regime:{assessment_id}",
        known_at=regime.known_at,
        evidence=[basis, *flagged],
    )


def record_regime(
    session: Session,
    rules: RegimeRuleSet,
    at: datetime,
    system_time: datetime,
    trigger: str,
) -> UUID | None:
    """Store the regime at T and, when the stress state changed since the previous assessment,
    a market-wide alert under the active alert rules (if they ask for it); None when T is
    assessed already."""
    set_actor(session, ACTOR)
    previous = session.scalar(
        select(RegimeAssessment.stress)
        .where(RegimeAssessment.rule_version == rules.rule_version, RegimeAssessment.known_at < at)
        .order_by(RegimeAssessment.known_at.desc())
        .limit(1)
    )
    regime = regime_at(session, rules, at, system_time)
    backfilled = system_time > at
    assessment_id = session.execute(
        insert(RegimeAssessment)
        .values(
            known_at=at,
            system_time=system_time,
            rule_version=rules.rule_version,
            stress=regime.stress,
            quadrant=regime.quadrant,
            flags_on=regime.flags_on,
            flags_available=regime.flags_available,
            assessment=regime.model_dump(mode="json"),
            backfilled=backfilled,
            trigger=trigger,
        )
        .on_conflict_do_nothing(constraint="uq_regime_assessments_known_at_rule")
        .returning(RegimeAssessment.id)
    ).scalar()
    if assessment_id is None:
        return None
    alert_rules = stored_alert_rules(session)
    if (
        alert_rules is not None
        and "stress_change" in alert_rules.market_events
        and alert_rules.regime_rule_version == rules.rule_version
        and previous is not None
        and regime.stress is not None
        and previous != regime.stress
    ):
        insert_alert(
            session,
            alert_rules,
            None,
            None,
            _stress_alert(regime, previous, assessment_id),
            system_time,
            None,
            backfilled,
        )
    return assessment_id
