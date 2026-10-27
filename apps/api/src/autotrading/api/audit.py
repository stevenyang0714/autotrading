"""Audit log viewer API (M0.9, ADR-019): read-only, newest first.

audit_log is written by database triggers on every audited table: inserts, updates and
deletes of registry rows (sources, entities, instruments, identifiers, entity relationships,
macro series, dead letters), supersedes of fact rows, and each valuation assumption version
saved from the web app (M1.3a). An update or supersede records each
changed field as {old, new}; a delete records the removed row. Objects are named where the
row still exists (a source id, a ticker, a company or series name).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.db.models import (
    Alert,
    AlertAcknowledgement,
    AlertRuleSet,
    AuditLog,
    BacktestRuleSet,
    DeadLetter,
    Entity,
    EntityRelationship,
    FactorDefinitionSet,
    FinancialFact,
    HoldingEntry,
    Identifier,
    Instrument,
    MacroObservation,
    MacroSeries,
    MomentumRuleSet,
    PriceBar,
    RegimeRuleSet,
    RiskCheck,
    RiskRuleSet,
    RotationRuleSet,
    Source,
    ThesisCard,
    TradeDecision,
    ValuationAssumptionSet,
)

router = APIRouter(tags=["audit"])

AuditAction = Literal["insert", "update", "delete", "supersede"]


class FieldChange(BaseModel):
    field: str
    old: Any
    new: Any


class AuditEntry(BaseModel):
    id: int
    occurred_at: datetime
    actor: str
    action: str
    table: str
    object_id: str
    object_label: str | None
    before_hash: str | None
    after_hash: str | None
    changes: list[FieldChange]  # update and supersede: each changed field
    removed: dict[str, Any] | None  # delete: the row as it was


class FacetCount(BaseModel):
    value: str
    count: int


class AuditFacets(BaseModel):
    tables: list[FacetCount]
    actions: list[FacetCount]
    actors: list[FacetCount]


class AuditLogPage(BaseModel):
    entries: list[AuditEntry]
    matching: int  # entries matching the filters, all pages
    next_before_id: int | None  # pass as before_id for the next (older) page
    facets: AuditFacets  # the whole log, for the filter choices


def _uuids(ids: list[str]) -> list[UUID]:
    out = []
    for value in ids:
        try:
            out.append(UUID(value))
        except ValueError:
            continue
    return out


def _decision_label(row: TradeDecision) -> str:
    """ "paper TRADE buy 10", "paper exit sell 10" or "NO TRADE (priced in)"."""
    if row.decision == "no_trade":
        return f"NO TRADE ({(row.no_trade_reason or '').replace('_', ' ')})"
    kind = "exit" if row.exits_decision_id else "TRADE"
    return f"paper {kind} {row.side} {row.quantity}"


def _labels(session: Session, table: str, ids: list[str]) -> dict[str, str]:
    """Readable names for objects that still exist; others keep their id."""
    resolvers: dict[str, Callable[[], list[tuple[Any, str]]]] = {
        "sources": lambda: [
            (row.id, row.name) for row in session.scalars(select(Source).where(Source.id.in_(ids)))
        ],
        "macro_series": lambda: [
            (row.id, row.title or row.id)
            for row in session.scalars(select(MacroSeries).where(MacroSeries.id.in_(ids)))
        ],
        "entities": lambda: [
            (row.id, row.name)
            for row in session.scalars(select(Entity).where(Entity.id.in_(_uuids(ids))))
        ],
        "instruments": lambda: [
            (row.instrument_id, f"{row.id_value} ({row.instrument_type})")
            for row in session.execute(
                select(Identifier.instrument_id, Identifier.id_value, Instrument.instrument_type)
                .join(Instrument, Instrument.id == Identifier.instrument_id)
                .where(
                    Identifier.instrument_id.in_(_uuids(ids)),
                    Identifier.id_type == "ticker",
                    Identifier.valid_to.is_(None),
                )
                .order_by(Identifier.id_namespace.desc())  # sec before alpaca
            )
        ],
        "identifiers": lambda: [
            (row.id, f"{row.id_namespace} {row.id_type} {row.id_value}")
            for row in session.scalars(select(Identifier).where(Identifier.id.in_(_uuids(ids))))
        ],
        "entity_relationships": lambda: [
            (row.id, row.relationship_type.replace("_", " "))
            for row in session.scalars(
                select(EntityRelationship).where(EntityRelationship.id.in_(_uuids(ids)))
            )
        ],
        "dead_letters": lambda: [
            (row.id, row.job)
            for row in session.scalars(select(DeadLetter).where(DeadLetter.id.in_(_uuids(ids))))
        ],
        "macro_observations": lambda: [
            (row.id, f"{row.series_id} {row.observation_date}")
            for row in session.scalars(
                select(MacroObservation).where(MacroObservation.id.in_(_uuids(ids)))
            )
        ],
        "price_bars": lambda: [
            (row.id, f"{row.symbol} {row.adjustment} {row.bar_date}")
            for row in session.scalars(select(PriceBar).where(PriceBar.id.in_(_uuids(ids))))
        ],
        "financial_facts": lambda: [
            (row.id, f"{row.metric_id} {row.period_end}")
            for row in session.scalars(
                select(FinancialFact).where(FinancialFact.id.in_(_uuids(ids)))
            )
        ],
        "valuation_assumptions": lambda: [
            (row.id, f"{row.id_value} assumptions v{row.version}")
            for row in session.execute(
                select(
                    ValuationAssumptionSet.id, ValuationAssumptionSet.version, Identifier.id_value
                )
                .join(Identifier, Identifier.instrument_id == ValuationAssumptionSet.instrument_id)
                .where(
                    ValuationAssumptionSet.id.in_(_uuids(ids)),
                    Identifier.id_type == "ticker",
                    Identifier.valid_to.is_(None),
                )
                .order_by(Identifier.id_namespace.desc())  # sec before alpaca
            )
        ],
        "thesis_cards": lambda: [
            (row.id, f"{row.ticker} thesis card v{row.version}")
            for row in session.scalars(select(ThesisCard).where(ThesisCard.id.in_(_uuids(ids))))
        ],
        "alerts": lambda: [
            (row.id, f"alert: {row.title}")
            for row in session.scalars(select(Alert).where(Alert.id.in_(_uuids(ids))))
        ],
        "alert_acknowledgements": lambda: [
            (row.id, f"acknowledged: {title}")
            for row, title in session.execute(
                select(AlertAcknowledgement, Alert.title)
                .join(Alert, Alert.id == AlertAcknowledgement.alert_id)
                .where(AlertAcknowledgement.id.in_(_uuids(ids)))
            )
        ],
        "risk_rule_sets": lambda: [
            (row.id, f"risk rules {row.rule_version}")
            for row in session.scalars(select(RiskRuleSet).where(RiskRuleSet.id.in_(_uuids(ids))))
        ],
        "risk_checks": lambda: [
            (row.id, f"risk check {row.ticker} {row.side} {row.quantity}: {row.verdict}")
            for row in session.scalars(select(RiskCheck).where(RiskCheck.id.in_(_uuids(ids))))
        ],
        "momentum_rule_sets": lambda: [
            (row.id, f"momentum rules {row.rule_version}")
            for row in session.scalars(
                select(MomentumRuleSet).where(MomentumRuleSet.id.in_(_uuids(ids)))
            )
        ],
        "backtest_rule_sets": lambda: [
            (row.id, f"backtest rules {row.rule_version}")
            for row in session.scalars(
                select(BacktestRuleSet).where(BacktestRuleSet.id.in_(_uuids(ids)))
            )
        ],
        "rotation_rule_sets": lambda: [
            (row.id, f"rotation rules {row.rule_version}")
            for row in session.scalars(
                select(RotationRuleSet).where(RotationRuleSet.id.in_(_uuids(ids)))
            )
        ],
        "factor_definition_sets": lambda: [
            (row.id, f"factor definitions {row.definition_version}")
            for row in session.scalars(
                select(FactorDefinitionSet).where(FactorDefinitionSet.id.in_(_uuids(ids)))
            )
        ],
        "regime_rule_sets": lambda: [
            (row.id, f"regime rules {row.rule_version}")
            for row in session.scalars(
                select(RegimeRuleSet).where(RegimeRuleSet.id.in_(_uuids(ids)))
            )
        ],
        "alert_rule_sets": lambda: [
            (row.id, f"alert rules {row.rule_version}")
            for row in session.scalars(select(AlertRuleSet).where(AlertRuleSet.id.in_(_uuids(ids))))
        ],
        "trade_decisions": lambda: [
            (row.id, f"{row.ticker} {_decision_label(row)}")
            for row in session.scalars(
                select(TradeDecision).where(TradeDecision.id.in_(_uuids(ids)))
            )
        ],
        "holding_entries": lambda: [
            (row.id, f"holdings {row.kind} {row.symbol or row.currency} ({row.account})")
            for row in session.scalars(select(HoldingEntry).where(HoldingEntry.id.in_(_uuids(ids))))
        ],
    }
    resolve = resolvers.get(table)
    if resolve is None or not ids:
        return {}
    labels: dict[str, str] = {}
    for key, label in resolve():
        labels.setdefault(str(key), label)
    return labels


def _facets(session: Session, column: Any) -> list[FacetCount]:
    rows = session.execute(
        select(column, func.count()).group_by(column).order_by(func.count().desc(), column)
    )
    return [FacetCount(value=value, count=count) for value, count in rows]


def _entry(row: AuditLog, label: str | None) -> AuditEntry:
    details = row.details or {}
    changes: list[FieldChange] = []
    removed = None
    if row.action in ("update", "supersede"):
        changes = [
            FieldChange(field=field, old=diff.get("old"), new=diff.get("new"))
            for field, diff in sorted(details.items())
            if isinstance(diff, dict)
        ]
    elif row.action == "delete":
        removed = details
    return AuditEntry(
        id=row.id,
        occurred_at=row.occurred_at,
        actor=row.actor,
        action=row.action,
        table=row.object_type,
        object_id=row.object_id,
        object_label=label,
        before_hash=row.before_hash,
        after_hash=row.after_hash,
        changes=changes,
        removed=removed,
    )


@router.get("/audit-log")
def audit_log(
    session: SessionDep,
    table: Annotated[str | None, Query(description="Audited table, e.g. sources")] = None,
    action: AuditAction | None = None,
    actor: Annotated[str | None, Query(description="e.g. ingest:sec_edgar")] = None,
    object_id: Annotated[str | None, Query(description="One object's history")] = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    before_id: Annotated[int | None, Query(ge=1, description="Older than this entry")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditLogPage:
    filters = []
    if table:
        filters.append(AuditLog.object_type == table)
    if action:
        filters.append(AuditLog.action == action)
    if actor:
        filters.append(AuditLog.actor == actor)
    if object_id:
        filters.append(AuditLog.object_id == object_id)
    if since:
        filters.append(AuditLog.occurred_at >= since)
    if until:
        filters.append(AuditLog.occurred_at <= until)
    matching = session.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    page = [*filters, AuditLog.id < before_id] if before_id else filters
    rows = session.scalars(
        select(AuditLog).where(*page).order_by(AuditLog.id.desc()).limit(limit + 1)
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    by_table: dict[str, list[str]] = {}
    for row in rows:
        by_table.setdefault(row.object_type, []).append(row.object_id)
    labels = {
        (table_name, key): label
        for table_name, ids in by_table.items()
        for key, label in _labels(session, table_name, ids).items()
    }
    return AuditLogPage(
        entries=[_entry(row, labels.get((row.object_type, row.object_id))) for row in rows],
        matching=matching,
        next_before_id=rows[-1].id if more and rows else None,
        facets=AuditFacets(
            tables=_facets(session, AuditLog.object_type),
            actions=_facets(session, AuditLog.action),
            actors=_facets(session, AuditLog.actor),
        ),
    )
