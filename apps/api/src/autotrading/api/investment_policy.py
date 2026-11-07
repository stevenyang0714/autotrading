"""Steven's investment policy (M3.12, ADR-043 IP12): his versions, and the version in force at T
against his holdings.

- GET /holdings/policy: the version in force at T (default now) as recorded now; each holding
  with its sleeve and weight; each sleeve, asset class and market with its target and drift;
  the positions above the cap; and, when a sleeve is outside its band, the whole-share trades
  that would bring every sleeve to its target and the cash they move in each currency.
- GET /holdings/policy/versions: every version, the newest first.
- POST /holdings/policy: a new version (the latest + 1), audited as `web`; earlier versions never
  change. Unknown fields are refused.
- Arithmetic on Steven's own targets, not advice. The policy stays on this machine with the
  holdings, and nothing here is pushed or sent to a broker (ADR-041 H12).
"""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic_core import to_jsonable_python
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.holdings import (
    HoldingFxOut,
    HoldingMarkOut,
    display_name,
    fx_out,
    issuer_names,
)
from autotrading.api.research import KnownAt
from autotrading.db.models import InvestmentPolicy
from autotrading.domain.investment_policy import (
    REBALANCING_VERSION,
    AssetClass,
    PolicyContent,
    SleeveMarket,
)
from autotrading.domain.markets import Market
from autotrading.repositories.investment_policy import assessment_at, save_version, versions

router = APIRouter(tags=["holdings"])

DETAIL = (
    "Arithmetic on your own targets, not advice: the policy is yours as you wrote it, and the "
    "trades are what would bring every sleeve back to its target at the last closes known, in "
    "whole shares, without fees or taxes. Kept on this machine only; nothing here is ever sent "
    "to a broker."
)


class PolicyVersionOut(BaseModel):
    version: int
    content: PolicyContent
    content_sha256: str
    reason: str
    recorded_at: datetime


class PolicyVersionsOut(BaseModel):
    versions: list[PolicyVersionOut]  # newest first


class PolicyHoldingOut(BaseModel):
    key: str  # US:SPY, TW:2330, USD
    market: Market | None
    instrument_id: UUID | None
    symbol: str | None
    name: str | None
    name_zh: str | None
    currency: str
    quantity: Decimal | None
    price: Decimal | None
    mark: HoldingMarkOut | None
    value: Decimal
    value_usd: Decimal | None
    weight: Decimal | None
    sleeve: str | None  # None: no sleeve names it
    over_cap: bool
    flags: list[str]


class SleeveDriftOut(BaseModel):
    name: str
    asset_class: AssetClass
    market: SleeveMarket
    target: Decimal
    band: Decimal
    actual: Decimal | None
    drift: Decimal | None
    outside: bool
    after: Decimal | None


class GroupDriftOut(BaseModel):
    group: str
    target: Decimal
    actual: Decimal | None
    drift: Decimal | None


class PolicyTradeOut(BaseModel):
    sleeve: str
    key: str
    market: Market
    instrument_id: UUID | None
    symbol: str
    name: str | None
    name_zh: str | None
    currency: str
    side: str
    amount_usd: Decimal
    price: Decimal | None
    mark: HoldingMarkOut | None
    shares: Decimal | None
    amount: Decimal | None
    weight_before: Decimal
    weight_target: Decimal
    flags: list[str]


class CashFlowOut(BaseModel):
    currency: str
    balance: Decimal
    flow: Decimal
    after: Decimal


class PolicyAssessmentOut(BaseModel):
    known_at: datetime
    system_time: datetime
    rebalancing_version: str
    policy: PolicyVersionOut | None
    equity_usd: Decimal | None
    fx: HoldingFxOut | None
    position_cap: Decimal | None  # a share of the total
    holdings: list[PolicyHoldingOut]
    sleeves: list[SleeveDriftOut]
    asset_classes: list[GroupDriftOut]
    markets: list[GroupDriftOut]
    due: bool
    blocked: list[str]
    trades: list[PolicyTradeOut]
    cash_flows: list[CashFlowOut]
    detail: str


class NewPolicy(BaseModel):
    """A version as written on the policy page. Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    content: PolicyContent
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _now(session: Session) -> datetime:
    return session.execute(select(func.now())).scalar_one()


def _version_out(row: InvestmentPolicy) -> PolicyVersionOut:
    return PolicyVersionOut(
        version=row.version,
        content=PolicyContent.model_validate(row.content),
        content_sha256=row.content_sha256,
        reason=row.reason,
        recorded_at=row.recorded_at,
    )


def _named(raw: dict[str, Any], issuers: dict[UUID, str]) -> dict[str, Any]:
    symbol = raw["key"].split(":")[1] if ":" in raw["key"] else None
    instrument_id = UUID(raw["instrument_id"]) if raw["instrument_id"] else None
    name, name_zh = display_name(symbol, instrument_id, issuers) if symbol else (None, None)
    return {**raw, "symbol": symbol, "name": name, "name_zh": name_zh}


@router.get("/holdings/policy")
def investment_policy(session: SessionDep, known_at: KnownAt = None) -> PolicyAssessmentOut:
    """The version in force at T (default now) against the holdings at T, as recorded now."""
    now = _now(session)
    assessment = assessment_at(session, known_at or now, now)
    stored: dict[str, Any] = to_jsonable_python(asdict(assessment))
    issuers = issuer_names(
        session,
        {h.instrument_id for h in assessment.holdings if h.instrument_id}
        | {t.instrument_id for t in assessment.trades if t.instrument_id},
    )
    policy = assessment.policy
    cap = policy.content.position_cap_pct if policy else None
    return PolicyAssessmentOut(
        known_at=assessment.known_at,
        system_time=assessment.system_time,
        rebalancing_version=REBALANCING_VERSION,
        policy=(
            PolicyVersionOut(
                version=policy.version,
                content=policy.content,
                content_sha256=policy.content.content_sha256(),
                reason=policy.reason,
                recorded_at=policy.recorded_at,
            )
            if policy
            else None
        ),
        equity_usd=assessment.equity_usd,
        fx=fx_out(session, assessment.fx, assessment.fx_lag_days),
        position_cap=cap / 100 if cap is not None else None,
        holdings=[PolicyHoldingOut.model_validate(_named(h, issuers)) for h in stored["holdings"]],
        sleeves=[SleeveDriftOut.model_validate(s) for s in stored["sleeves"]],
        asset_classes=[GroupDriftOut.model_validate(g) for g in stored["asset_classes"]],
        markets=[GroupDriftOut.model_validate(g) for g in stored["markets"]],
        due=assessment.due,
        blocked=list(assessment.blocked),
        trades=[PolicyTradeOut.model_validate(_named(t, issuers)) for t in stored["trades"]],
        cash_flows=[CashFlowOut.model_validate(f) for f in stored["cash_flows"]],
        detail=DETAIL,
    )


@router.get("/holdings/policy/versions")
def investment_policy_versions(session: SessionDep) -> PolicyVersionsOut:
    return PolicyVersionsOut(versions=[_version_out(row) for row in versions(session)])


@router.post("/holdings/policy", status_code=201)
def save_investment_policy(body: NewPolicy, session: SessionDep) -> PolicyVersionOut:
    """A new version (the latest + 1); earlier versions are never changed."""
    row = save_version(session, body.content, body.reason)
    try:
        session.commit()
    except IntegrityError as exc:  # another version was saved at the same moment
        session.rollback()
        raise HTTPException(
            status_code=409, detail="another version was just saved; reload and try again"
        ) from exc
    session.refresh(row)
    return _version_out(row)
