"""Convergence assessments and alerts (M1.7, ADR-028): the events and buyback readings of one
company as known at (T, S), and the rows they produce, in the caller's transaction.

`record_convergence` runs with each buyback state assignment under the alert rules' buyback
rule version: it stores the company's level at the assignment's T, an alert when the level
changes (L1 or above on either side), and, unless backfilling, an L0 alert for each event since
the previous assessment (at most `event_lookback_days` back). Re-running is harmless: one
assessment per company, T and rule version, one alert per rule version and source.
"""

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.db.models import (
    Alert,
    BuybackStateAssignment,
    ConvergenceAssessment,
    Filing,
    FilingBuybackStatement,
)
from autotrading.db.models import (
    AlertRuleSet as AlertRuleSetRow,
)
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION
from autotrading.domain.convergence import (
    AlertIn,
    AlertRuleSet,
    AlertRulesFile,
    BuybackReading,
    Condition,
    Convergence,
    Event,
    assess,
    event_alert,
    level_alert,
    new_events,
)
from autotrading.repositories.audit import set_actor
from autotrading.settings import get_settings

logger = logging.getLogger(__name__)
ACTOR = "rules:alert_rules"


def load_alert_rules(path: Path | None = None) -> AlertRulesFile:
    path = path or get_settings().resolved_config_dir() / "alert_rules.yaml"
    return AlertRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _file() -> AlertRulesFile:
    return load_alert_rules()


def active_alert_version() -> str:
    return _file().active().rule_version


def stored_alert_rules(session: Session, rule_version: str | None = None) -> AlertRuleSet | None:
    """A released alert rule set as `make migrate` registered it; None when not loaded."""
    version = rule_version or active_alert_version()
    row = session.scalars(
        select(AlertRuleSetRow).where(AlertRuleSetRow.rule_version == version)
    ).first()
    return AlertRuleSet.model_validate(row.content) if row else None


def convergence_rules(session: Session) -> AlertRuleSet | None:
    """The active alert rules as stored; None (and a warning) before `make migrate` loads them."""
    rules = stored_alert_rules(session)
    if rules is None:
        logger.warning(
            "alert rule set %s is not loaded (make migrate): no convergence assessed",
            active_alert_version(),
        )
    return rules


# ---------- inputs at (T, S) ----------


def buyback_reading(
    assignment_id: object, state: str, known_at: datetime, rule_version: str, assessment: Any
) -> BuybackReading:
    return BuybackReading(
        assignment_id=str(assignment_id),
        state=state,
        known_at=known_at,
        rule_version=rule_version,
        conditions={
            c["condition_id"]: Condition(c["status"], c.get("value"))
            for c in assessment.get("conditions", [])
        },
    )


def events_at(
    session: Session,
    rules: AlertRuleSet,
    instrument_id: UUID,
    chain: list[UUID],
    since: datetime,
    at: datetime,
    system_time: datetime,
) -> list[Event]:
    """The company's Phase 1 events public in (since, T], filings and statements as this
    database held them at S. Buyback state changes count at their assignment's T."""
    found: list[Event] = []
    kinds = set(rules.event_kinds)
    if kinds & {"periodic_report", "earnings_release"}:
        for f in session.scalars(
            select(Filing).where(
                Filing.entity_id.in_(chain),
                Filing.published_at > since,
                Filing.published_at <= at,
                Filing.recorded_at <= system_time,
                or_(
                    Filing.form.in_(("10-K", "10-Q")),
                    (Filing.form == "8-K") & Filing.items.contains("2.02"),
                ),
            )
        ):
            kind = "earnings_release" if f.form == "8-K" else "periodic_report"
            if kind not in kinds:
                continue
            label = (
                f"Earnings release (8-K 2.02) {f.accession_number}"
                if kind == "earnings_release"
                else f"{f.form} {f.accession_number}"
            )
            found.append(
                Event(kind, "filings", str(f.id), f.accession_number, f.published_at, label)
            )
    if "buyback_statement" in kinds:
        for s in session.scalars(
            select(FilingBuybackStatement).where(
                FilingBuybackStatement.entity_id.in_(chain),
                FilingBuybackStatement.extractor_version == EXTRACTOR_VERSION,
                FilingBuybackStatement.kind.in_(rules.buyback_statement_kinds),
                FilingBuybackStatement.published_at > since,
                FilingBuybackStatement.published_at <= at,
                FilingBuybackStatement.recorded_at <= system_time,
            )
        ):
            label = f"Buyback {s.kind} announced ({s.document_type} {s.accession_number})"
            found.append(
                Event(
                    "buyback_statement",
                    "filing_buyback_statements",
                    str(s.id),
                    s.accession_number,
                    s.published_at,
                    label,
                )
            )
    if "buyback_state_change" in kinds:
        history = session.execute(
            select(
                BuybackStateAssignment.id,
                BuybackStateAssignment.state,
                BuybackStateAssignment.known_at,
            )
            .where(
                BuybackStateAssignment.instrument_id == instrument_id,
                BuybackStateAssignment.rule_version == rules.buyback_rule_version,
                BuybackStateAssignment.known_at <= at,
            )
            .order_by(BuybackStateAssignment.known_at)
        ).all()
        for before, row in pairwise(history):
            if row.state != before.state and since < row.known_at <= at:
                found.append(
                    Event(
                        "buyback_state_change",
                        "buyback_state_assignments",
                        str(row.id),
                        f"buyback_state_assignments:{row.id}",
                        row.known_at,
                        f"Buyback state {_state(row.state)} (was {_state(before.state)})",
                    )
                )
    return found


def _state(state: str) -> str:
    return state.replace("_", "-").upper()


# ---------- writing ----------


def _insert_alert(
    session: Session,
    rules: AlertRuleSet,
    instrument_id: UUID,
    ticker: str,
    alert: AlertIn,
    system_time: datetime,
    assessment_id: UUID | None,
    backfilled: bool,
) -> bool:
    inserted = session.execute(
        insert(Alert)
        .values(
            rule_version=rules.rule_version,
            instrument_id=instrument_id,
            ticker=ticker,
            kind=alert.kind,
            level=alert.level,
            previous_level=alert.previous_level,
            direction=alert.direction,
            title=alert.title,
            source_key=alert.source_key,
            known_at=alert.known_at,
            system_time=system_time,
            assessment_id=assessment_id,
            evidence=alert.evidence,
            backfilled=backfilled,
        )
        .on_conflict_do_nothing(constraint="uq_alerts_rule_version_source_key")
        .returning(Alert.id)
    ).scalar()
    return inserted is not None


def convergence_at(
    session: Session,
    rules: AlertRuleSet,
    instrument_id: UUID,
    chain: list[UUID],
    reading: BuybackReading | None,
    at: datetime,
    system_time: datetime,
) -> tuple[Convergence, list[Event]]:
    """The assessment at (T, S) and the events it read (the window and the alert lookback)."""
    days = max(rules.levels.watch.window_days, rules.event_lookback_days)
    events = events_at(
        session, rules, instrument_id, chain, at - timedelta(days=days), at, system_time
    )
    return assess(rules, at, reading, events), events


def record_convergence(
    session: Session,
    rules: AlertRuleSet,
    instrument_id: UUID,
    ticker: str,
    chain: list[UUID],
    reading: BuybackReading,
    at: datetime,
    system_time: datetime,
    trigger: str,
) -> UUID | None:
    """Store the company's level at T and its alerts; None when T is assessed already."""
    if reading.rule_version != rules.buyback_rule_version:
        return None
    set_actor(session, ACTOR)
    previous = session.execute(
        select(ConvergenceAssessment.level, ConvergenceAssessment.known_at)
        .where(
            ConvergenceAssessment.instrument_id == instrument_id,
            ConvergenceAssessment.rule_version == rules.rule_version,
            ConvergenceAssessment.known_at < at,
        )
        .order_by(ConvergenceAssessment.known_at.desc())
        .limit(1)
    ).first()
    result, events = convergence_at(session, rules, instrument_id, chain, reading, at, system_time)
    backfilled = system_time > at
    assessment_id = session.execute(
        insert(ConvergenceAssessment)
        .values(
            instrument_id=instrument_id,
            ticker=ticker,
            known_at=at,
            system_time=system_time,
            rule_version=rules.rule_version,
            buyback_assignment_id=UUID(reading.assignment_id),
            level=result.level,
            assessment=result.model_dump(mode="json"),
            backfilled=backfilled,
            trigger=trigger,
        )
        .on_conflict_do_nothing(constraint="uq_convergence_assessments_instrument_known_at_rule")
        .returning(ConvergenceAssessment.id)
    ).scalar()
    if assessment_id is None:
        return None
    change = level_alert(
        ticker, result, previous.level if previous else None, f"level:{assessment_id}"
    )
    if change is not None:
        _insert_alert(
            session, rules, instrument_id, ticker, change, system_time, assessment_id, backfilled
        )
    if trigger != "backfill":
        since = previous.known_at if previous else None
        for event in new_events(events, since, at, rules.event_lookback_days):
            _insert_alert(
                session,
                rules,
                instrument_id,
                ticker,
                event_alert(ticker, event),
                system_time,
                None,
                False,
            )
    return assessment_id


def seed_event_alerts(
    session: Session,
    rules: AlertRuleSet,
    instrument_id: UUID,
    ticker: str,
    chain: list[UUID],
    at: datetime,
) -> int:
    """L0 alerts for the events of the last `event_lookback_days` (going live, A3)."""
    set_actor(session, ACTOR)
    events = events_at(
        session,
        rules,
        instrument_id,
        chain,
        at - timedelta(days=rules.event_lookback_days),
        at,
        at,
    )
    return sum(
        _insert_alert(
            session, rules, instrument_id, ticker, event_alert(ticker, e), at, None, False
        )
        for e in new_events(events, None, at, rules.event_lookback_days)
    )
