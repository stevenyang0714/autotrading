"""Glossary Registry API (02 §22, M0.4): complete terms only, latest version first."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on

from autotrading.api.data_health import SessionDep
from autotrading.db.models import GlossaryTermRow

router = APIRouter(tags=["glossary"])


class GlossaryTermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    term_id: str
    methodology_version: str
    display_name: str
    category: str
    short_definition: str
    full_definition: str
    formula: str
    unit: str
    example: str
    direction: str
    interpretation: str
    why_it_matters: str
    source: str
    source_url: str
    as_of: str
    update_cadence: str
    caveats: str
    related_terms: list[str]
    loaded_at: datetime


class GlossaryVersion(BaseModel):
    methodology_version: str
    loaded_at: datetime


class GlossaryTermDetail(BaseModel):
    term: GlossaryTermOut
    versions: list[GlossaryVersion]


@router.get("/glossary")
def list_terms(session: SessionDep, category: str | None = None) -> list[GlossaryTermOut]:
    query = (
        select(GlossaryTermRow)
        .ext(distinct_on(GlossaryTermRow.term_id))
        .order_by(GlossaryTermRow.term_id, GlossaryTermRow.loaded_at.desc())
    )
    if category is not None:
        query = query.where(GlossaryTermRow.category == category)
    return [GlossaryTermOut.model_validate(row) for row in session.scalars(query)]


@router.get("/glossary/{term_id}")
def get_term(term_id: str, session: SessionDep) -> GlossaryTermDetail:
    rows = session.scalars(
        select(GlossaryTermRow)
        .where(GlossaryTermRow.term_id == term_id)
        .order_by(GlossaryTermRow.loaded_at.desc())
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"unknown glossary term {term_id!r}")
    return GlossaryTermDetail(
        term=GlossaryTermOut.model_validate(rows[0]),
        versions=[
            GlossaryVersion(methodology_version=r.methodology_version, loaded_at=r.loaded_at)
            for r in rows
        ],
    )
