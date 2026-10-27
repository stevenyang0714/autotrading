"""Exchange-published measures (M3.7, ADR-039 TW7): insert-only with the fact version rules
(`apply_versions`), and point-in-time reads (`known_at`, `system_time`)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from autotrading.db.models import ExchangeMeasure
from autotrading.domain.provenance import Provenance
from autotrading.repositories.audit import set_actor
from autotrading.repositories.facts import BatchResult, Incoming, apply_versions, as_of_query


@dataclass(frozen=True)
class MeasureIn:
    instrument_id: UUID
    symbol: str
    session_date: date
    measure_id: str
    value: Decimal
    unit: str  # TWD, percent, x or lots
    detail: str | None
    data_mode: str  # live, or fixture for recorded test data
    provenance: Provenance

    def fact_key(self) -> tuple[Any, ...]:
        return (self.instrument_id, self.measure_id, self.session_date)


def measure_key(row: ExchangeMeasure) -> tuple[Any, ...]:
    return (row.instrument_id, row.measure_id, row.session_date)


def insert_measures(session: Session, items: Iterable[MeasureIn], *, actor: str) -> BatchResult:
    set_actor(session, actor)
    incoming = [
        Incoming(
            item=m,
            key=m.fact_key(),
            published_at=m.provenance.published_at,
            value=m.value,
            label=f"{m.symbol} {m.measure_id} {m.session_date}",
        )
        for m in items
    ]
    if not incoming:
        return BatchResult(0, 0, [])
    existing = session.scalars(
        select(ExchangeMeasure)
        .where(
            ExchangeMeasure.instrument_id.in_({i.item.instrument_id for i in incoming}),
            ExchangeMeasure.measure_id.in_({i.item.measure_id for i in incoming}),
            ExchangeMeasure.session_date.in_({i.item.session_date for i in incoming}),
        )
        .order_by(ExchangeMeasure.published_at, ExchangeMeasure.recorded_at, ExchangeMeasure.id)
    )

    def build(m: MeasureIn, version: int, latest: ExchangeMeasure | None) -> ExchangeMeasure:
        return ExchangeMeasure(
            id=uuid4(),
            instrument_id=m.instrument_id,
            symbol=m.symbol,
            session_date=m.session_date,
            measure_id=m.measure_id,
            value=m.value,
            unit=m.unit,
            detail=m.detail,
            data_mode=m.data_mode,
            **m.provenance.model_dump(),
            version=version,
            supersedes_id=latest.id if latest is not None else None,
            revision_reason="revision" if latest is not None else None,
        )

    new_rows, result = apply_versions(existing, measure_key, incoming, build)
    session.add_all(new_rows)
    session.flush()
    return result


def measures(
    session: Session,
    instrument_id: UUID,
    measure_ids: Sequence[str],
    *,
    known_at: datetime,
    system_time: datetime | None = None,
    since: date | None = None,
    until: date | None = None,
) -> list[ExchangeMeasure]:
    """Each measure's value per session as known at `known_at` and held at `system_time`
    (default: now), oldest session first."""
    known = as_of_query(ExchangeMeasure, known_at=known_at, system_time=system_time).where(
        ExchangeMeasure.instrument_id == instrument_id,
        ExchangeMeasure.measure_id.in_(list(measure_ids)),
    )
    if since is not None:
        known = known.where(ExchangeMeasure.session_date >= since)
    if until is not None:
        known = known.where(ExchangeMeasure.session_date <= until)
    row = aliased(ExchangeMeasure, known.subquery())
    return list(session.scalars(select(row).order_by(row.session_date, row.measure_id)))


def latest_session(
    session: Session,
    instrument_ids: Iterable[UUID],
    measure_id: str,
    *,
    before: date | None = None,
) -> date | None:
    """The latest session any of the instruments has a current value of a measure for
    (strictly before `before` when given)."""
    query = select(ExchangeMeasure.session_date).where(
        ExchangeMeasure.instrument_id.in_(list(instrument_ids)),
        ExchangeMeasure.measure_id == measure_id,
        ExchangeMeasure.superseded_at.is_(None),
    )
    if before is not None:
        query = query.where(ExchangeMeasure.session_date < before)
    return session.scalar(query.order_by(ExchangeMeasure.session_date.desc()).limit(1))


def values_on(
    session: Session, instrument_ids: Iterable[UUID], measure_ids: Sequence[str], day: date
) -> dict[UUID, dict[str, Decimal]]:
    """The current stored values of the measures on one session: instrument -> measure ->
    value."""
    out: dict[UUID, dict[str, Decimal]] = {}
    rows = session.scalars(
        select(ExchangeMeasure).where(
            ExchangeMeasure.instrument_id.in_(list(instrument_ids)),
            ExchangeMeasure.measure_id.in_(list(measure_ids)),
            ExchangeMeasure.session_date == day,
            ExchangeMeasure.superseded_at.is_(None),
        )
    )
    for row in rows:
        out.setdefault(row.instrument_id, {})[row.measure_id] = row.value
    return out
