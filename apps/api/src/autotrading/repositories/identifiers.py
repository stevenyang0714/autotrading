"""Identifier lookups with validity periods (ticker, CIK; namespace per provider convention)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.db.models import Identifier


def current_identifier(
    session: Session, id_type: str, namespace: str, value: str
) -> Identifier | None:
    """The open-ended identifier row for a value (at most one, by exclusion constraint)."""
    return session.scalars(
        select(Identifier).where(
            Identifier.id_type == id_type,
            Identifier.id_namespace == namespace,
            Identifier.id_value == value,
            Identifier.valid_to.is_(None),
        )
    ).first()


def current_identifier_of(
    session: Session, id_type: str, namespace: str, *, instrument_id: UUID
) -> Identifier | None:
    return session.scalars(
        select(Identifier).where(
            Identifier.id_type == id_type,
            Identifier.id_namespace == namespace,
            Identifier.instrument_id == instrument_id,
            Identifier.valid_to.is_(None),
        )
    ).first()


def close_identifier(identifier: Identifier, at: datetime) -> None:
    """End a validity period; a new row starts at the same instant ('[)' ranges touch)."""
    identifier.valid_to = at
