"""Alerts Center (M1.7, ADR-028): convergence levels L0-L4 per company and in-app alerts with
their rule version, evidence and acknowledgement. Alerts stay in the app (P1-1).

- `GET /alerts`: alerts known at T, newest first; open (not acknowledged by T) by default.
- `GET /alerts/{id}`: one alert with the convergence assessment behind it.
- `POST /alerts/{id}/acknowledge`: once per alert, with an optional note; audited (actor web).
- `GET /convergence`: each company's level at T and the checks behind it.
- `GET /alerts/rules`: the released alert rule sets.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.fair_value import ACTOR
from autotrading.api.instruments import universe_equities
from autotrading.api.research import KnownAt
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import (
    JOURNAL_USER,
    Alert,
    AlertAcknowledgement,
    ConvergenceAssessment,
    Filing,
    FilingBuybackStatement,
)
from autotrading.db.models import (
    AlertRuleSet as AlertRuleSetRow,
)
from autotrading.domain.convergence import Item, LevelCheck, level_name
from autotrading.domain.regime import STRESS_ORDER
from autotrading.repositories.audit import set_actor
from autotrading.repositories.convergence import active_alert_version, load_alert_rules

router = APIRouter(tags=["alerts"])
STRESS_NAMES = {order: name.upper() for name, order in STRESS_ORDER.items()}  # regime alerts

IN_APP_ONLY = (
    "In-app alerts only (P1-1). Levels are deterministic rules; none places an order. L4 needs "
    "the company's standard paper position to pass the risk check (paper only)."
)
URLS: dict[str, Any] = {"filings": Filing, "filing_buyback_statements": FilingBuybackStatement}


class AlertEvidenceOut(BaseModel):
    table: str
    id: str
    label: str
    url: str | None  # the filing on EDGAR; None for a buyback state (see the company page)


class AcknowledgementOut(BaseModel):
    acknowledged_at: datetime
    note: str | None


class AlertOut(BaseModel):
    id: UUID
    rule_version: str
    ticker: str | None  # None: a market-wide alert (kinds regime, portfolio and rotation)
    kind: Literal["event", "level_change", "regime", "portfolio", "rotation"]
    level: int
    level_name: str
    previous_level: int | None
    direction: Literal["up", "down"] | None
    title: str
    known_at: datetime
    system_time: datetime
    backfilled: bool
    evidence: list[AlertEvidenceOut]
    assessment_id: UUID | None
    acknowledgement: AcknowledgementOut | None


class AlertsOut(BaseModel):
    known_at: datetime
    rule_version: str
    status: Literal["open", "acknowledged", "all"]
    open_by_level: dict[str, int]  # open alerts at T (live only), by level
    entries: list[AlertOut]
    detail: str = IN_APP_ONLY


class CompanyLevel(BaseModel):
    ticker: str
    known_at: datetime  # of the assessment
    level: int | None
    level_name: str
    backfilled: bool
    levels: list[LevelCheck]
    items: list[Item]
    independent_families: list[int]


class ConvergenceOut(BaseModel):
    known_at: datetime
    rule_version: str
    companies: list[CompanyLevel]
    detail: str = IN_APP_ONLY


class AlertDetail(AlertOut):
    assessment: CompanyLevel | None


class AlertRuleSetOut(BaseModel):
    rule_version: str
    status: Literal["active", "retired"]
    released: date
    content: dict[str, Any]
    content_sha256: str


class AcknowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str | None = Field(default=None, max_length=500)


def _evidence(session: Session, rows: list[Alert]) -> dict[tuple[str, str], str]:
    """EDGAR links of the filings and statements the alerts cite."""
    links: dict[tuple[str, str], str] = {}
    for table, model in URLS.items():
        ids = {UUID(e["id"]) for row in rows for e in row.evidence if e["table"] == table}
        if ids:
            for row_id, url in session.execute(
                select(model.id, model.source_url).where(model.id.in_(ids))
            ):
                links[(table, str(row_id))] = url
    return links


def _acknowledgements(
    session: Session, ids: list[UUID], at: datetime | None
) -> dict[UUID, AlertAcknowledgement]:
    query = select(AlertAcknowledgement).where(AlertAcknowledgement.alert_id.in_(ids))
    if at is not None:
        query = query.where(AlertAcknowledgement.acknowledged_at <= at)
    return {a.alert_id: a for a in session.scalars(query)}


def kind_level_name(kind: str, level: int) -> str:
    """A company alert's convergence level; a market-wide alert's own state (ADR-029, ADR-031,
    ADR-032)."""
    if kind == "regime":
        return STRESS_NAMES[level]
    if kind == "portfolio":
        return "DRAWDOWN" if level else "WITHIN LIMIT"
    if kind == "rotation":
        return "S3 TARGET"
    return level_name(level)


def alert_out(
    row: Alert, links: dict[tuple[str, str], str], ack: AlertAcknowledgement | None
) -> AlertOut:
    return AlertOut(
        id=row.id,
        rule_version=row.rule_version,
        ticker=row.ticker,
        kind=row.kind,  # type: ignore[arg-type]
        level=row.level,
        level_name=kind_level_name(row.kind, row.level),
        previous_level=row.previous_level,
        direction=row.direction,  # type: ignore[arg-type]
        title=row.title,
        known_at=row.known_at,
        system_time=row.system_time,
        backfilled=row.backfilled,
        evidence=[
            AlertEvidenceOut(
                table=e["table"],
                id=e["id"],
                label=e["label"],
                url=links.get((e["table"], e["id"])),
            )
            for e in row.evidence
        ],
        assessment_id=row.assessment_id,
        acknowledgement=AcknowledgementOut(acknowledged_at=ack.acknowledged_at, note=ack.note)
        if ack
        else None,
    )


def company_level(row: ConvergenceAssessment) -> CompanyLevel:
    stored = row.assessment
    return CompanyLevel(
        ticker=row.ticker,
        known_at=row.known_at,
        level=row.level,
        level_name=level_name(row.level),
        backfilled=row.backfilled,
        levels=[LevelCheck.model_validate(c) for c in stored["levels"]],
        items=[Item.model_validate(i) for i in stored["items"]],
        independent_families=stored["independent_families"],
    )


@router.get("/alerts/rules")
def alert_rules(session: SessionDep) -> list[AlertRuleSetOut]:
    file = load_alert_rules()
    status = {r.rule_version: r.status for r in file.rule_sets}
    rows = session.scalars(select(AlertRuleSetRow).order_by(AlertRuleSetRow.loaded_at.desc()))
    return [
        AlertRuleSetOut(
            rule_version=row.rule_version,
            status=status.get(row.rule_version, "retired"),
            released=row.released,
            content=row.content,
            content_sha256=row.content_sha256,
        )
        for row in rows
    ]


@router.get("/alerts")
def alerts(
    session: SessionDep,
    known_at: KnownAt = None,
    status: Literal["open", "acknowledged", "all"] = "open",
    level_min: int = Query(default=0, ge=0, le=3),
    ticker: str | None = None,
    include_backfilled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> AlertsOut:
    at = known_at_or_now(session, known_at)
    version = active_alert_version()
    base = select(Alert).where(Alert.rule_version == version, Alert.known_at <= at)
    if not include_backfilled:
        base = base.where(Alert.backfilled.is_(False))
    acked = select(AlertAcknowledgement.alert_id).where(AlertAcknowledgement.acknowledged_at <= at)
    query = base.where(Alert.level >= level_min)
    if ticker:
        query = query.where(Alert.ticker == ticker.upper())
    if status == "open":
        query = query.where(Alert.id.not_in(acked))
    elif status == "acknowledged":
        query = query.where(Alert.id.in_(acked))
    rows = list(session.scalars(query.order_by(Alert.known_at.desc(), Alert.title).limit(limit)))
    links = _evidence(session, rows)
    acks = _acknowledgements(session, [r.id for r in rows], at)
    open_by_level = {
        level_name(level): count
        for level, count in session.execute(
            select(Alert.level, func.count())
            .where(
                Alert.rule_version == version,
                Alert.known_at <= at,
                Alert.backfilled.is_(False),
                Alert.id.not_in(acked),
            )
            .group_by(Alert.level)
            .order_by(Alert.level)
        )
    }
    return AlertsOut(
        known_at=at,
        rule_version=version,
        status=status,
        open_by_level=open_by_level,
        entries=[alert_out(r, links, acks.get(r.id)) for r in rows],
    )


def _alert_detail(session: Session, row: Alert) -> AlertDetail:
    ack = _acknowledgements(session, [row.id], None).get(row.id)
    out = alert_out(row, _evidence(session, [row]), ack)
    assessment = (
        session.get(ConvergenceAssessment, row.assessment_id) if row.assessment_id else None
    )
    return AlertDetail(
        **out.model_dump(),
        assessment=company_level(assessment) if assessment else None,
    )


@router.get("/alerts/{alert_id}")
def alert(alert_id: UUID, session: SessionDep) -> AlertDetail:
    row = session.get(Alert, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no alert {alert_id}")
    return _alert_detail(session, row)


@router.post("/alerts/{alert_id}/acknowledge", status_code=201)
def acknowledge(alert_id: UUID, body: AcknowledgeIn, session: SessionDep) -> AlertDetail:
    """Acknowledge once (ADR-028 A4); the alert itself never changes. Audited."""
    row = session.get(Alert, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no alert {alert_id}")
    set_actor(session, ACTOR)
    session.add(AlertAcknowledgement(alert_id=row.id, note=body.note or None, user_id=JOURNAL_USER))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="this alert is acknowledged already") from exc
    return _alert_detail(session, row)


@router.get("/convergence")
def convergence(session: SessionDep, known_at: KnownAt = None) -> ConvergenceOut:
    """Each universe company's latest assessment at or before T."""
    at = known_at_or_now(session, known_at)
    version = active_alert_version()
    rows = session.scalars(
        select(ConvergenceAssessment)
        .where(
            ConvergenceAssessment.rule_version == version,
            ConvergenceAssessment.known_at <= at,
        )
        .ext(distinct_on(ConvergenceAssessment.instrument_id))
        .order_by(ConvergenceAssessment.instrument_id, ConvergenceAssessment.known_at.desc())
    ).all()
    by_ticker = {r.ticker: r for r in rows}
    tickers = [t for t, _, _ in universe_equities(session)]
    companies = [company_level(by_ticker[t]) for t in tickers if t in by_ticker]
    companies.sort(key=lambda c: (-(c.level if c.level is not None else -1), c.ticker))
    return ConvergenceOut(known_at=at, rule_version=version, companies=companies)
