"""M0.9 audit log viewer (ADR-019): the triggers' audit rows read back through GET /audit-log,
newest first, with filters, paging, field-level changes, deleted rows and readable object names.
Uses its own migrated database."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.config_sync import load_sources, sync_sources
from autotrading.main import create_app
from autotrading.repositories.audit import set_actor
from autotrading.settings import get_settings
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    sources = load_sources(get_settings().resolved_config_dir() / "sources.yaml")
    with Session(engine) as session:
        sync_sources(session, sources)  # one insert per source, actor config:sources.yaml
        session.commit()
        # A config change: one update with its changed fields.
        changed = sources.model_copy(
            update={
                "sources": [
                    s.model_copy(update={"priority": 99}) if s.id == "gdelt" else s
                    for s in sources.sources
                ]
            }
        )
        sync_sources(session, changed)
        session.commit()
        # A deleted row: a source nothing refers to.
        set_actor(session, "test:delete")
        session.execute(
            text(
                "INSERT INTO sources (id, name, url, tier, license_status, access_status, "
                "update_cadence, freshness_sla_seconds, enabled, priority, topics, "
                "rate_limit_per_second, rate_limit_burst) VALUES ('audit_probe', 'Probe', "
                "'https://example.com', 4, 'unknown', 'disabled', 'daily', 60, false, 0, "
                "'{}', 1, 1)"
            )
        )
        session.execute(text("DELETE FROM sources WHERE id = 'audit_probe'"))
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(
        create_app(health_checker=OkChecker(), sessions=sessionmaker(engine))
    ) as client:
        yield client


def test_updates_show_each_changed_field(client: TestClient) -> None:
    body = client.get("/audit-log", params={"table": "sources", "action": "update"}).json()
    (entry,) = [e for e in body["entries"] if e["object_id"] == "gdelt"]
    changes = {c["field"]: (c["old"], c["new"]) for c in entry["changes"]}
    assert changes["priority"] == (40, 99)
    assert entry["actor"] == "config:sources.yaml"
    assert entry["object_label"] == "GDELT DOC 2.0 API"
    assert entry["before_hash"] and entry["after_hash"] and entry["removed"] is None


def test_deletes_keep_the_removed_row(client: TestClient) -> None:
    body = client.get("/audit-log", params={"action": "delete"}).json()
    (entry,) = body["entries"]
    assert (entry["actor"], entry["table"], entry["object_id"]) == (
        "test:delete",
        "sources",
        "audit_probe",
    )
    assert entry["removed"]["name"] == "Probe"
    assert entry["object_label"] is None  # the row is gone: its id is shown
    assert entry["after_hash"] is None


def test_newest_first_with_paging(client: TestClient) -> None:
    first = client.get("/audit-log", params={"limit": 5}).json()
    ids = [e["id"] for e in first["entries"]]
    assert ids == sorted(ids, reverse=True) and len(ids) == 5
    assert first["matching"] > 5 and first["next_before_id"] == ids[-1]
    second = client.get("/audit-log", params={"limit": 5, "before_id": ids[-1]}).json()
    assert max(e["id"] for e in second["entries"]) < ids[-1]
    everything = client.get("/audit-log", params={"limit": 200}).json()
    assert everything["next_before_id"] is None
    assert len(everything["entries"]) == everything["matching"]


def test_filters_and_facets(client: TestClient) -> None:
    params = {"table": "sources", "object_id": "gdelt", "actor": "config:sources.yaml"}
    body = client.get("/audit-log", params=params).json()
    assert [e["action"] for e in body["entries"]] == ["update", "insert"]
    tables = {f["value"]: f["count"] for f in body["facets"]["tables"]}
    actions = {f["value"]: f["count"] for f in body["facets"]["actions"]}
    assert tables["sources"] >= 2 and set(actions) >= {"insert", "update", "delete"}
    assert client.get("/audit-log", params={"action": "rename"}).status_code == 422


def test_the_audit_log_stays_append_only(engine: Engine) -> None:
    from sqlalchemy.exc import DBAPIError

    with engine.connect() as conn, pytest.raises(DBAPIError, match=r"append-only|TRUNCATE"):
        conn.execute(text("DELETE FROM audit_log"))


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    recorded: tuple[tuple[str, dict[str, str | int]], ...] = (
        ("audit-log", {"limit": 50}),
        ("audit-log-sources-updates", {"table": "sources", "action": "update"}),
        ("audit-log-deletes", {"action": "delete"}),
    )
    for name, params in recorded:
        response = client.get("/audit-log", params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "config sync, a config change and a deleted probe source in the "
            "integration test database (tests/integration/test_audit.py)",
            "endpoint": "/audit-log",
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
