"""Insert-only access to macro observations (M0.6): the same version rules as financial facts
(`apply_versions`), with ALFRED revisions stored as new versions (ADR-012, ADR-015)."""

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.db.models import MacroObservation
from autotrading.domain.macro import MacroObservationIn
from autotrading.repositories.audit import set_actor
from autotrading.repositories.facts import BatchResult, Incoming, apply_versions


def observation_key(row: MacroObservation) -> tuple[Any, ...]:
    return (row.series_id, row.observation_date)


class MacroObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert_many(self, observations: Iterable[MacroObservationIn], *, actor: str) -> BatchResult:
        set_actor(self.session, actor)
        incoming = [
            Incoming(
                item=obs,
                key=obs.fact_key(),
                published_at=obs.provenance.published_at,
                value=obs.value,
                label=f"{obs.series_id} {obs.observation_date} (vintage {obs.vintage})",
            )
            for obs in observations
        ]
        if not incoming:
            return BatchResult(0, 0, [])
        existing = self.session.scalars(
            select(MacroObservation)
            .where(MacroObservation.series_id.in_({i.item.series_id for i in incoming}))
            .order_by(
                MacroObservation.published_at, MacroObservation.recorded_at, MacroObservation.id
            )
        )

        def build(
            obs: MacroObservationIn, version: int, latest: MacroObservation | None
        ) -> MacroObservation:
            return MacroObservation(
                id=uuid4(),  # set now so a later version in the batch can point at it
                **obs.model_dump(exclude={"provenance"}),
                **obs.provenance.model_dump(),
                version=version,
                supersedes_id=latest.id if latest is not None else None,
                revision_reason="revision" if latest is not None else None,
            )

        new_rows, result = apply_versions(existing, observation_key, incoming, build)
        self.session.add_all(new_rows)
        self.session.flush()
        return result
