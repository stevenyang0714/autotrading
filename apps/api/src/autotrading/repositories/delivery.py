"""Alert delivery outside the app (M3.0b, ADR-037): the alerts the active delivery rules push and
have not sent yet, and the ledger of every attempt, in the caller's transaction.

`deliver` sends each pending alert through a `send(text) -> message id` callable (the chat id
stays inside it, never here), records `sent` or `failed` in alert_deliveries and commits after
each, so a crash never sends twice. A partial unique index allows one `sent` per alert and
channel; a failed alert is tried again on the next run, up to the rules' `max_attempts`.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.adapters.telegram.client import TelegramError
from autotrading.db.models import Alert, AlertDelivery, DigestDelivery
from autotrading.db.models import DeliveryRuleSet as DeliveryRuleSetRow
from autotrading.domain.delivery import (
    DIGEST_TITLES,
    LEVEL_ZH,
    DeliveryRuleSet,
    DeliveryRulesFile,
    Facts,
    StoredAlert,
    digest,
    message,
    not_pushed,
)
from autotrading.repositories.alert_context import alert_context
from autotrading.repositories.audit import set_actor
from autotrading.settings import get_settings

ACTOR = "delivery:telegram"


def load_delivery_rules(path: Path | None = None) -> DeliveryRulesFile:
    path = path or get_settings().resolved_config_dir() / "delivery_rules.yaml"
    return DeliveryRulesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _file() -> DeliveryRulesFile:
    return load_delivery_rules()


def active_delivery_version() -> str:
    return _file().active().rule_version


def stored_delivery_rules(
    session: Session, rule_version: str | None = None
) -> DeliveryRuleSet | None:
    """A released delivery rule set as `make migrate` registered it; None when not loaded."""
    version = rule_version or active_delivery_version()
    row = session.scalars(
        select(DeliveryRuleSetRow).where(DeliveryRuleSetRow.rule_version == version)
    ).first()
    return DeliveryRuleSet.model_validate(row.content) if row else None


def stored_alert(row: Alert) -> StoredAlert:
    return StoredAlert(
        id=str(row.id),
        rule_version=row.rule_version,
        kind=row.kind,
        level=row.level,
        previous_level=row.previous_level,
        title=row.title,
        known_at=row.known_at,
        backfilled=row.backfilled,
        evidence=list(row.evidence),
        direction=row.direction,
        ticker=row.ticker,
    )


def pending(session: Session, rules: DeliveryRuleSet, now: datetime) -> list[Alert]:
    """The alerts these rules push that were not sent and have attempts left, oldest first,
    at most `max_per_run`."""
    sent = select(AlertDelivery.alert_id).where(
        AlertDelivery.channel == rules.channel, AlertDelivery.status == "sent"
    )
    failures = (
        select(AlertDelivery.alert_id)
        .where(AlertDelivery.channel == rules.channel, AlertDelivery.status == "failed")
        .group_by(AlertDelivery.alert_id)
        .having(func.count() >= rules.max_attempts)
    )
    rows = session.scalars(
        select(Alert)
        .where(
            Alert.rule_version == rules.alert_rule_version,
            Alert.backfilled.is_(False),
            Alert.kind.in_(rules.kinds),
            Alert.known_at >= now - timedelta(hours=rules.max_age_hours),
            Alert.id.not_in(sent),
            Alert.id.not_in(failures),
        )
        .order_by(Alert.known_at, Alert.created_at)
    ).all()
    chosen = [r for r in rows if not_pushed(rules, stored_alert(r), now) is None]
    return chosen[: rules.max_per_run]


def record(
    session: Session,
    rules: DeliveryRuleSet,
    alert_id: UUID,
    *,
    message_id: int | None = None,
    error_code: int | None = None,
    error: str | None = None,
) -> bool:
    """Store one attempt; False when a `sent` row exists already (never sent twice)."""
    set_actor(session, ACTOR)
    status = "sent" if message_id is not None else "failed"
    stored = session.execute(
        insert(AlertDelivery)
        .values(
            alert_id=alert_id,
            channel=rules.channel,
            rule_version=rules.rule_version,
            status=status,
            message_id=message_id,
            error_code=error_code,
            error=error[:300] if error else None,
        )
        .on_conflict_do_nothing(
            index_elements=[AlertDelivery.alert_id, AlertDelivery.channel],
            index_where=AlertDelivery.status == "sent",
        )
        .returning(AlertDelivery.id)
    ).scalar()
    return stored is not None


def deliver(
    session: Session,
    rules: DeliveryRuleSet,
    send: Callable[[str], int],
    now: datetime,
    acquire: Callable[[], None] = lambda: None,
) -> tuple[int, int]:
    """Send every pending alert once, outside quiet hours; returns (sent, failed)."""
    if rules.quiet_hours.holds(now):
        return 0, 0
    sent = failed = 0
    for row in pending(session, rules, now):
        context = alert_context(session, row) if rules.details else None
        text = message(rules, stored_alert(row), context)
        acquire()
        try:
            message_id = send(text)
        except TelegramError as exc:
            record(session, rules, row.id, error_code=exc.code, error=str(exc))
            failed += 1
        else:
            record(session, rules, row.id, message_id=message_id)
            sent += 1
        session.commit()
    return sent, failed


def delivered(
    session: Session, alert_ids: Iterable[UUID], channel: str = "telegram"
) -> dict[UUID, datetime]:
    """When each alert was sent on the channel (for the Alerts Center)."""
    ids = list(alert_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(AlertDelivery.alert_id, AlertDelivery.attempted_at).where(
            AlertDelivery.alert_id.in_(ids),
            AlertDelivery.channel == channel,
            AlertDelivery.status == "sent",
        )
    ).all()
    return {alert_id: at for alert_id, at in rows}


# ---------- the weekly digest (M3.0c, ADR-038) ----------


def digest_week(rules: DeliveryRuleSet, now: datetime) -> date:
    """The Monday of the local week `now` falls in."""
    local = now.astimezone(ZoneInfo(rules.quiet_hours.timezone)).date()
    return local - timedelta(days=local.weekday())


def digest_due(rules: DeliveryRuleSet, now: datetime) -> bool:
    """Whether the scheduled digest is due at `now`: its weekday and hour, local time."""
    if rules.digest is None:
        return False
    local = now.astimezone(ZoneInfo(rules.quiet_hours.timezone))
    return local.weekday() == rules.digest.weekday and local.hour == rules.digest.at.hour


def digest_sent(session: Session, rules: DeliveryRuleSet, week: date) -> bool:
    return (
        session.scalars(
            select(DigestDelivery.id).where(
                DigestDelivery.channel == rules.channel,
                DigestDelivery.week == week,
                DigestDelivery.status == "sent",
            )
        ).first()
        is not None
    )


def digest_sections(
    session: Session, now: datetime
) -> tuple[str | None, str | None, list[tuple[str, list[Facts]]]]:
    """(stress, quadrant, sections) of the digest: the Opportunity Radar's candidates at `now`
    (S4 target, S1 companies at L3/L4, S3 target), each with its facts."""
    # imported here: api.alerts imports this module, and api.candidates imports api.alerts
    from autotrading.api.candidates import _companies, _context, _etfs, _momentum
    from autotrading.repositories.alert_context import _conditions, _sectors, company_facts
    from autotrading.repositories.convergence import stored_alert_rules

    alert_rules = stored_alert_rules(session)
    buyback = alert_rules.buyback_rule_version if alert_rules else None
    sectors = _sectors(session, (alert_rules.risk_rule_version if alert_rules else None) or "0.1.0")
    context = _context(session, now)

    def facts(symbol: str, weight: object, conditions: list[object], note: str | None) -> Facts:
        found = company_facts(
            session,
            symbol,
            now,
            now,
            sectors,
            weight=None if weight is None else Decimal(str(weight)),
            conditions=_conditions({"items": conditions}, "items"),
            buyback_rule_version=buyback,
        )
        return replace(found, note=note)

    s4 = [
        facts(
            c.ticker, c.weight_pct, [r.model_dump(mode="json") for r in c.reading.conditions], None
        )
        for c in _momentum(session, now)
    ]
    s1 = [
        facts(c.ticker, None, [], LEVEL_ZH.get(c.convergence.level or 0))
        for c in _companies(session, now)
    ]
    s3 = [
        facts(c.ticker, c.weight_pct, [r.model_dump(mode="json") for r in c.reading.trend], None)
        for c in _etfs(session, now)
    ]
    sections = [(DIGEST_TITLES["S4"], s4), (DIGEST_TITLES["S1"], s1), (DIGEST_TITLES["S3"], s3)]
    return (context.stress if context else None, context.quadrant if context else None, sections)


def deliver_digest(
    session: Session,
    rules: DeliveryRuleSet,
    send: Callable[[str], int],
    now: datetime,
    *,
    force: bool = False,
) -> int:
    """Send the week's digest once (when due, or `force`); returns the messages sent."""
    if rules.digest is None or (not force and not digest_due(rules, now)):
        return 0
    week = digest_week(rules, now)
    if digest_sent(session, rules, week):
        return 0
    stress, quadrant, sections = digest_sections(session, now)
    texts = digest(rules, week, stress, quadrant, sections)
    set_actor(session, ACTOR)
    first: int | None = None
    try:
        for text in texts:
            message_id = send(text)
            first = message_id if first is None else first
    except TelegramError as exc:
        session.add(
            DigestDelivery(
                week=week,
                channel=rules.channel,
                rule_version=rules.rule_version,
                status="failed",
                messages=0,
                error_code=exc.code,
                error=str(exc)[:300],
            )
        )
        session.commit()
        return 0
    session.add(
        DigestDelivery(
            week=week,
            channel=rules.channel,
            rule_version=rules.rule_version,
            status="sent",
            messages=len(texts),
            message_id=first,
        )
    )
    session.commit()
    return len(texts)
