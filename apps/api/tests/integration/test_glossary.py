"""M0.4: glossary registry sync (versioned, append-only) and the /glossary API."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.config_sync import GlossaryVersionError, load_glossary, sync_glossary
from autotrading.db.models import GlossaryTermRow
from autotrading.domain.glossary import GlossaryFile
from autotrading.infra.probes import ProbeResult
from autotrading.main import create_app
from autotrading.settings import get_settings

pytestmark = pytest.mark.integration

GLOSSARY = load_glossary(get_settings().resolved_glossary_path())


class OkChecker:
    def core(self) -> dict[str, ProbeResult]:
        return {}

    def background(self) -> dict[str, ProbeResult]:
        return {}


def with_term(glossary: GlossaryFile, term_id: str, **changes: Any) -> GlossaryFile:
    terms = [t.model_copy(update=changes) if t.term_id == term_id else t for t in glossary.terms]
    return glossary.model_copy(update={"terms": terms})


@pytest.fixture(scope="module")
def synced(engine: Engine) -> Engine:
    with Session(engine) as session:
        sync_glossary(session, GLOSSARY)
        session.commit()
    return engine


def test_sync_registers_complete_terms_once(synced: Engine) -> None:
    with Session(synced) as session:
        again = sync_glossary(session, GLOSSARY)
        session.commit()
        count = session.scalar(select(func.count()).select_from(GlossaryTermRow))
    assert again.created == []
    assert len(again.unchanged) == len(GLOSSARY.complete_terms())
    assert count == len(GLOSSARY.complete_terms())  # seed terms are not registered


def test_changed_content_without_version_bump_is_refused(synced: Engine) -> None:
    edited = with_term(GLOSSARY, "rate_limit", caveats="Edited without a bump.")
    with Session(synced) as session, pytest.raises(GlossaryVersionError, match="rate_limit"):
        sync_glossary(session, edited)


def test_version_bump_adds_a_new_version(synced: Engine) -> None:
    bumped = with_term(
        GLOSSARY, "freshness_sla", caveats="New wording.", methodology_version="0.1.1"
    )
    with Session(synced) as session:
        result = sync_glossary(session, bumped)
        session.commit()
    assert result.created == ["freshness_sla"]
    with TestClient(
        create_app(health_checker=OkChecker(), sessions=sessionmaker(synced))
    ) as client:
        detail = client.get("/glossary/freshness_sla").json()
        listed = {t["term_id"]: t for t in client.get("/glossary").json()}
        missing = client.get("/glossary/not_a_term")
        navigation = client.get("/glossary", params={"category": "navigation"}).json()
    assert detail["term"]["methodology_version"] == "0.1.1"
    assert [v["methodology_version"] for v in detail["versions"]] == ["0.1.1", "0.1.0"]
    assert listed["freshness_sla"]["methodology_version"] == "0.1.1"
    assert listed["data_freshness"]["short_definition"]
    assert missing.status_code == 404
    assert {t["term_id"] for t in navigation} >= {"planned_phase", "dashboard_earnings"}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE glossary_terms SET short_definition = 'x' WHERE term_id = 'dead_letter'",
        "DELETE FROM glossary_terms WHERE term_id = 'dead_letter'",
        "TRUNCATE glossary_terms",
    ],
)
def test_glossary_versions_are_immutable(synced: Engine, statement: str) -> None:
    with synced.connect() as conn, pytest.raises(DBAPIError, match=r"append-only|TRUNCATE"):
        conn.execute(text(statement))
