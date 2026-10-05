"""Insert-only access to bitemporal fact tables (ADR-007, ADR-012).

Two clocks:
- known_at    -> compared with published_at: what the world could know at that time.
- system_time -> compared with recorded_at / superseded_at: what this database held then.

Source-side revisions (restatements) are new rows with a later published_at, so an earlier
known_at still returns the original value. Our own corrections supersede the wrong row in
system time, so only an earlier system_time returns it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from autotrading.db.mixins import FactMixin
from autotrading.db.models import FinancialFact
from autotrading.domain.facts import FinancialFactIn, RevisionReason
from autotrading.repositories.audit import set_actor


class FactConflictError(RuntimeError):
    """The new version cannot be ordered against existing versions of the same fact."""


@dataclass(frozen=True)
class InsertResult:
    fact: FinancialFact
    created: bool


def key_matches(model: type[FactMixin], values: dict[str, Any]) -> ColumnElement[bool]:
    # IS NOT DISTINCT FROM: NULL key parts (e.g. period_start of an instant) compare equal.
    return and_(
        *(
            getattr(model, column).is_not_distinct_from(values[column])
            for column in model.__fact_key__
        )
    )


def visible_in_system_time(
    model: type[FactMixin], system_time: datetime | None
) -> ColumnElement[bool]:
    if system_time is None:
        return model.superseded_at.is_(None)
    return and_(
        model.recorded_at <= system_time,
        or_(model.superseded_at.is_(None), model.superseded_at > system_time),
    )


def as_of_query[FactT: FactMixin](
    model: type[FactT],
    *,
    known_at: datetime,
    effective_at: datetime | None = None,
    system_time: datetime | None = None,
) -> Select[FactT]:
    """Latest version per fact key known at `known_at`, as this database held it at
    `system_time` (default: now). Ties on published_at go to the later recorded row."""
    key_columns = [getattr(model, column) for column in model.__fact_key__]
    conditions = [model.published_at <= known_at, visible_in_system_time(model, system_time)]
    if effective_at is not None:
        conditions.append(model.effective_from <= effective_at)
        conditions.append(or_(model.effective_to.is_(None), model.effective_to >= effective_at))
    return (
        select(model)
        .where(*conditions)
        .ext(distinct_on(*key_columns))
        .order_by(
            *key_columns,
            model.published_at.desc(),
            model.recorded_at.desc(),
            getattr(model, "id").desc(),  # noqa: B009  (every fact table has an id column)
        )
    )


class FinancialFactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert(
        self, fact: FinancialFactIn, *, actor: str, reason: RevisionReason = "restatement"
    ) -> InsertResult:
        """Store a reported value. Writes a new version only when the value differs from the
        latest current version; later 10-Ks repeat prior-year comparatives unchanged."""
        set_actor(self.session, actor)
        key = self._key_values(fact)
        latest = self._latest_current(key)
        if latest is not None:
            if latest.value == fact.value:
                return InsertResult(latest, created=False)
            if fact.provenance.published_at <= latest.published_at:
                # Ingest in publication order; two values for one publication is a data error.
                raise FactConflictError(
                    f"{fact.metric_id}: value published at {fact.provenance.published_at} "
                    f"does not follow the current version published at {latest.published_at}"
                )
        row = self._build_row(
            fact,
            version=self._next_version(key),
            supersedes=latest.id if latest is not None else None,
            reason=reason if latest is not None else None,
            restated=latest is not None,
        )
        self.session.add(row)
        self.session.flush()
        return InsertResult(row, created=True)

    def correct(self, fact_id: UUID, corrected: FinancialFactIn, *, actor: str) -> FinancialFact:
        """Fix our own error: supersede the wrong row in system time and store the right value."""
        set_actor(self.session, actor)
        wrong = self.session.get(FinancialFact, fact_id, with_for_update=True)
        if wrong is None:
            raise LookupError(f"financial fact {fact_id} not found")
        key = self._key_values(corrected)
        if any(getattr(wrong, column) != key[column] for column in FinancialFact.__fact_key__):
            raise FactConflictError("a correction must keep the fact key of the corrected row")
        # The trigger replaces the value with the database clock.
        self.session.execute(
            update(FinancialFact)
            .where(FinancialFact.id == wrong.id)
            .values(superseded_at=func.now())
        )
        self.session.refresh(wrong)
        row = self._build_row(
            corrected,
            version=self._next_version(key),
            supersedes=wrong.id,
            reason="correction",
            restated=wrong.restated_flag,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def as_of(
        self,
        *,
        known_at: datetime,
        effective_at: datetime | None = None,
        system_time: datetime | None = None,
        entity_id: UUID | None = None,
        metric_id: str | None = None,
    ) -> list[FinancialFact]:
        query = as_of_query(
            FinancialFact, known_at=known_at, effective_at=effective_at, system_time=system_time
        )
        if entity_id is not None:
            query = query.where(FinancialFact.entity_id == entity_id)
        if metric_id is not None:
            query = query.where(FinancialFact.metric_id == metric_id)
        return list(self.session.scalars(query))

    def _key_values(self, fact: FinancialFactIn) -> dict[str, Any]:
        return dict(zip(FinancialFact.__fact_key__, fact.fact_key(), strict=True))

    def _latest_current(self, key: dict[str, Any]) -> FinancialFact | None:
        query = (
            select(FinancialFact)
            .where(key_matches(FinancialFact, key), FinancialFact.superseded_at.is_(None))
            .order_by(FinancialFact.published_at.desc(), FinancialFact.recorded_at.desc())
            .limit(1)
        )
        return self.session.scalars(query).first()

    def _next_version(self, key: dict[str, Any]) -> int:
        query = select(func.coalesce(func.max(FinancialFact.version), 0)).where(
            key_matches(FinancialFact, key)
        )
        return int(self.session.scalar(query) or 0) + 1

    @staticmethod
    def _build_row(
        fact: FinancialFactIn,
        *,
        version: int,
        supersedes: UUID | None,
        reason: RevisionReason | None,
        restated: bool,
    ) -> FinancialFact:
        return FinancialFact(
            **fact.model_dump(exclude={"provenance"}),
            **fact.provenance.model_dump(),
            version=version,
            supersedes_fact_id=supersedes,
            revision_reason=reason,
            restated_flag=restated,
        )
