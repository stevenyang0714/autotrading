"""Steven's investment policy (M3.12, ADR-043): the version in force at T as recorded by S, a
new version from the web app (audited as `web`), and the policy against the holdings at (T, S).
Holdings-side (ADR-041 H4): no rule, alert, push or risk check calls it."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autotrading.db.models import HOLDING_USER, InvestmentPolicy
from autotrading.domain.holdings import Valuation
from autotrading.domain.investment_policy import Assessment, Policy, PolicyContent, Quote, assess
from autotrading.domain.markets import MARKETS
from autotrading.repositories import holdings
from autotrading.repositories.audit import set_actor
from autotrading.repositories.prices import instruments_by_symbol

ACTOR = "web"


def policy_of(row: InvestmentPolicy) -> Policy:
    return Policy(
        version=row.version,
        content=PolicyContent.model_validate(row.content),
        reason=row.reason,
        recorded_at=row.recorded_at,
    )


def policy_at(session: Session, at: datetime, system_time: datetime) -> Policy | None:
    """The version in force at T as recorded by S: the latest recorded by both."""
    row = session.scalars(
        select(InvestmentPolicy)
        .where(InvestmentPolicy.recorded_at <= min(at, system_time))
        .order_by(InvestmentPolicy.version.desc())
        .limit(1)
    ).first()
    return policy_of(row) if row is not None else None


def versions(session: Session) -> list[InvestmentPolicy]:
    """Every version, the newest first."""
    return list(session.scalars(select(InvestmentPolicy).order_by(InvestmentPolicy.version.desc())))


def save_version(session: Session, content: PolicyContent, reason: str) -> InvestmentPolicy:
    """A new version (the latest + 1); earlier versions are never changed. The caller commits:
    a version saved at the same moment fails on the unique version."""
    set_actor(session, ACTOR)
    latest = session.scalar(select(func.max(InvestmentPolicy.version)))
    row = InvestmentPolicy(
        version=(latest or 0) + 1,
        content=content.content(),
        content_sha256=content.content_sha256(),
        reason=reason,
        user_id=HOLDING_USER,
    )
    session.add(row)
    return row


def quotes(
    session: Session, policy: Policy, valuation: Valuation, at: datetime, system_time: datetime
) -> dict[str, Quote]:
    """The last close known at T of each listing a sleeve names but nothing holds (by member
    key); a listing the database does not know is left out (its trade shows no close)."""
    held = {f"{p.market}:{p.symbol}" for p in valuation.positions}
    wanted = [
        m
        for s in policy.content.sleeves
        for m in s.members
        if m.market is not None and m.key not in held
    ]
    out: dict[str, Quote] = {}
    for market, spec in MARKETS.items():
        members = [m for m in wanted if m.market == market]
        if not members:
            continue
        ids = instruments_by_symbol(session, [m.symbol or "" for m in members], spec.namespace)
        for m in members:
            instrument_id = ids.get(m.symbol or "")
            if instrument_id is not None:
                out[m.key] = Quote(
                    instrument_id, holdings.last_mark(session, instrument_id, at, system_time)
                )
    return out


def assessment_at(session: Session, at: datetime, system_time: datetime) -> Assessment:
    """The policy in force at T against the holdings at T, as the database held both at S."""
    valuation = holdings.valuation_at(session, at, system_time)
    policy = policy_at(session, at, system_time)
    found = quotes(session, policy, valuation, at, system_time) if policy else {}
    return assess(valuation, policy, found)
