"""The Taiwan screens (M3.11, ADR-042): the latest judged run known at T and its history, read
from stored rows; nothing is evaluated on request.

- `/taiwan/screens`: the run's coverage, movers and each screen's watch list with the numbers
  and the bar each reading cites (feed, publication time, row id) for a spot check; each
  screen's definition in words from its rule version; a newer session not judged, with why.
- `/taiwan/screens/history`: every judged run of that rule version known at T, with how many
  stocks met each screen (the history check, SC13): never returns after the hits (OD-7).

A research screen and a watch list, not buy or sell advice; Taiwan stays out of every
strategy, alert and risk rule (ADR-039 TW12, amended by ADR-042 SC12 for the report only).
"""

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.api.taiwan import Attribution, attribution
from autotrading.api.valuation import known_at_or_now
from autotrading.db.models import ScreenRun
from autotrading.domain.screens import (
    HistorySummary,
    Liquidity,
    MoverRules,
    Readiness,
    ScreenRunOut,
    describe,
    history_summary,
)
from autotrading.repositories.listed import industry_names
from autotrading.repositories.screens import latest, stored_screen_rules

router = APIRouter(tags=["screens"])

DISCLAIMER = (
    "A research screen and a watch list, not buy or sell advice. Thresholds are Claude's "
    "defaults (ADR-042), unvalidated: the history check counts the stocks that met a screen, "
    "never their returns (OD-7)."
)


class ScreenDefinitionOut(BaseModel):
    screen_id: str
    name_zh: str
    conditions: list[str]
    notes: list[str]
    invalidation: list[str]


class ScreenRulesOut(BaseModel):
    rule_version: str
    content_sha256: str
    released: date
    note: str
    window_sessions: int
    watch_sessions: int
    readiness: Readiness
    liquidity: Liquidity
    movers: MoverRules
    definitions: list[ScreenDefinitionOut]


class PendingOut(BaseModel):
    """A session after the run's that was not judged, and why."""

    session: date
    reason: str
    known_at: datetime


class TaiwanScreensOut(BaseModel):
    known_at: datetime
    run_id: UUID | None
    recorded_at: datetime | None
    trigger: str | None
    backfilled: bool | None
    demo: bool  # recorded test data (the DEMO DATA banner, ADR-006)
    run: ScreenRunOut | None
    rules: ScreenRulesOut | None
    pending: PendingOut | None
    industries: dict[str, str]
    attribution: Attribution
    detail: str = DISCLAIMER


class HistoryPoint(BaseModel):
    session: date
    backfilled: bool
    movers: int
    meeting: dict[str, int]  # screen_id -> stocks that met it


class TaiwanScreensHistoryOut(BaseModel):
    known_at: datetime
    rule_version: str | None
    industry_basis: str | None
    points: list[HistoryPoint]
    summary: list[HistorySummary]
    detail: str = DISCLAIMER


def _rules_out(rule_version: str, session: SessionDep) -> ScreenRulesOut | None:
    rules = stored_screen_rules(session, rule_version)
    if rules is None:
        return None
    return ScreenRulesOut(
        rule_version=rules.rule_version,
        content_sha256=rules.content_sha256(),
        released=rules.released,
        note=rules.note,
        window_sessions=rules.window_sessions,
        watch_sessions=rules.watch_sessions,
        readiness=rules.readiness,
        liquidity=rules.liquidity,
        movers=rules.movers,
        definitions=[
            ScreenDefinitionOut(screen_id=s.screen_id, name_zh=s.name_zh, **describe(rules, s))
            for s in rules.screens
        ],
    )


def _demo(run: ScreenRunOut) -> bool:
    sources = [m.source for m in run.movers] + [
        x.source for s in run.screens for x in s.lines if x.source is not None
    ]
    return any(s.feed_status == "fixture" for s in sources)


@router.get("/taiwan/screens")
def taiwan_screens(session: SessionDep, known_at: KnownAt = None) -> TaiwanScreensOut:
    at = known_at_or_now(session, known_at)
    row = latest(session, known_at=at)
    run = ScreenRunOut.model_validate(row.document) if row else None
    pending_query = select(ScreenRun).where(
        ScreenRun.market == "TW", ScreenRun.status == "not_judged", ScreenRun.known_at <= at
    )
    if row is not None:
        pending_query = pending_query.where(ScreenRun.session > row.session)
    found = session.scalars(
        pending_query.order_by(ScreenRun.session.desc(), ScreenRun.recorded_at.desc()).limit(1)
    ).first()
    return TaiwanScreensOut(
        known_at=at,
        run_id=row.id if row else None,
        recorded_at=row.recorded_at if row else None,
        trigger=row.trigger if row else None,
        backfilled=row.backfilled if row else None,
        demo=_demo(run) if run else False,
        run=run,
        rules=_rules_out(row.rule_version, session) if row else None,
        pending=PendingOut(
            session=found.session, reason=found.reason or "", known_at=found.known_at
        )
        if found
        else None,
        industries=industry_names(),
        attribution=attribution(at, finmind=True),
    )


@router.get("/taiwan/screens/history")
def taiwan_screens_history(
    session: SessionDep, known_at: KnownAt = None
) -> TaiwanScreensHistoryOut:
    at = known_at_or_now(session, known_at)
    row = latest(session, known_at=at)
    if row is None:
        return TaiwanScreensHistoryOut(
            known_at=at, rule_version=None, industry_basis=None, points=[], summary=[]
        )
    rows = session.execute(
        select(
            ScreenRun.session,
            ScreenRun.backfilled,
            ScreenRun.counts,
            ScreenRun.document["industry_basis"].astext.label("basis"),
        )
        .where(
            ScreenRun.market == "TW",
            ScreenRun.status == "judged",
            ScreenRun.rule_version == row.rule_version,
            ScreenRun.known_at <= at,
        )
        .order_by(ScreenRun.session)
    ).all()
    counts = [r.counts for r in rows]
    screen_ids = list(row.counts.get("screens", {}))
    basis = {str(r.basis) for r in rows if r.backfilled}
    return TaiwanScreensHistoryOut(
        known_at=at,
        rule_version=row.rule_version,
        industry_basis=", ".join(sorted(basis)) or None,
        points=[
            HistoryPoint(
                session=r.session,
                backfilled=r.backfilled,
                movers=int(r.counts.get("movers", 0)),
                meeting={k: int(v["meeting"]) for k, v in r.counts.get("screens", {}).items()},
            )
            for r in rows
        ],
        summary=history_summary(screen_ids, counts),
    )
