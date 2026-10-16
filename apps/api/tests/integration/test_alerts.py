"""Alerts Center (M1.7, ADR-028) over the recorded SEC filings, Alpaca closes, FRED yields and
news: convergence levels stored with each buyback state assignment, alerts with their rule
version and evidence, acknowledgement audited."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.fred.series import FredSeriesJob
from autotrading.adapters.sec.refresh import universe_predecessors
from autotrading.api.buyback_states import evaluate_universe, load_rules
from autotrading.api.instruments import issuer_chain
from autotrading.config_sync import (
    AlertRulesVersionError,
    load_macro_series,
    load_risk_rules,
    load_sources,
    sync_alert_rules,
    sync_buyback_rules,
    sync_macro_series,
    sync_risk_rules,
    sync_sources,
)
from autotrading.db.models import (
    AuditLog,
    BuybackStateAssignment,
    ConvergenceAssessment,
    Filing,
    Instrument,
    Source,
)
from autotrading.domain.provenance import end_of_day
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.convergence import (
    buyback_reading,
    convergence_at,
    load_alert_rules,
    stored_alert_rules,
)
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay, news_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry, replay

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
VALUED_AT = datetime(2026, 10, 6, 12, tzinfo=UTC)  # the recorded closes end on 2026-10-05
MONTH_END = end_of_day(date(2026, 3, 31))
CONFIG = get_settings().resolved_config_dir()


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
    with Session(engine) as session:
        sync_sources(session, load_sources(CONFIG / "sources.yaml"))
        sync_macro_series(session, load_macro_series(CONFIG / "macro_series.yaml"))
        sync_risk_rules(session, load_risk_rules(CONFIG / "risk_rules.yaml"))
        sync_buyback_rules(session, load_rules())
        sync_alert_rules(session, load_alert_rules())
        for source in session.scalars(select(Source)):
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


@pytest.fixture(scope="module")
def stored(sessions: sessionmaker[Session]) -> Iterator[datetime]:
    """Replay the recorded data, then evaluate every universe equity at a month end and at
    VALUED_AT as the database holds it now (each with its convergence level and alerts)."""
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    runner = IngestionRunner(
        sessions,
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        news_replay.register_recorded(
            alpaca_replay.register_recorded(
                fred_replay.register_recorded(recorded_registry()), fixture=False
            ),
            fixture=False,
        ),
    )
    replay(
        runner,
        WINDOW,
        universe_predecessors(CONFIG),
        before_instances=lambda: alpaca_replay.replay_splits(runner, WINDOW),
    )
    for job, params in (
        ("alpaca.daily_bars", alpaca_replay.recorded_params("alpaca.daily_bars")),
        (
            FredSeriesJob.name,
            {"series_id": "DGS10", "observation_start": fred_replay.RECORDED_SERIES["DGS10"]},
        ),
    ):
        runner.execute(runner.create_run(job, params, WINDOW))
    news_replay.replay(runner, WINDOW)
    with sessions() as session:
        now = session.execute(select(func.now())).scalar_one()
        for at in (MONTH_END, VALUED_AT):
            evaluate_universe(session, at, now, "manual")
    yield now
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def client(sessions: sessionmaker[Session], stored: datetime) -> Iterator[TestClient]:
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        yield client


def iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def all_alerts(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "known_at": iso(VALUED_AT),
        "status": "all",
        "include_backfilled": True,
    } | params
    response = client.get("/alerts", params=query)
    assert response.status_code == 200, response.text
    entries: list[dict[str, Any]] = response.json()["entries"]
    return entries


def test_each_assignment_has_its_convergence_level(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        assignments = session.scalars(
            select(BuybackStateAssignment).where(BuybackStateAssignment.rule_version == "0.3.0")
        ).all()
        assessments = {
            a.buyback_assignment_id: a for a in session.scalars(select(ConvergenceAssessment))
        }
    assert len(assignments) == 6  # three companies at two dates
    assert set(assessments) == {a.id for a in assignments}
    for assignment in assignments:
        row = assessments[assignment.id]
        assert (row.rule_version, row.known_at, row.ticker) == (
            "0.3.0",  # since M2.3: L4 with the standard risk check, portfolio alerts
            assignment.known_at,
            assignment.ticker,
        )
        levels = row.assessment["levels"]
        assert [c["level"] for c in levels] == [0, 1, 2, 3, 4]
        # L4 reads the standard risk check (M2.3): fails without L3, passes or fails with it
        assert levels[4]["status"] in ("pass", "fail", "unavailable")
        assert levels[4]["detail"].startswith(("needs L3 first", "standard paper position"))
        assert row.assessment["buyback_rule_version"] == "0.3.0"
        if assignment.state in ("none", "watch"):
            assert row.level is None or row.level <= 1  # no thesis without executed buybacks


def test_recomputing_at_the_same_times_gives_the_same_assessment(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    # A filing recorded later, though public before T, does not change what was assessed.
    with sessions() as session:
        aapl = session.scalars(
            select(ConvergenceAssessment).where(
                ConvergenceAssessment.ticker == "AAPL", ConvergenceAssessment.known_at == VALUED_AT
            )
        ).one()
        apple = session.get_one(Instrument, aapl.instrument_id)
        template = session.scalars(
            select(Filing)
            .where(Filing.entity_id == apple.entity_id, Filing.form == "10-Q")
            .order_by(Filing.published_at.desc())
        ).first()
        assert template is not None
        session.execute(
            text(
                "INSERT INTO filings (entity_id, cik, accession_number, form, filing_date, "
                "accepted_at, report_date, items, source_id, source_tier, source_url, "
                "published_at, published_at_precision, ingested_at, effective_from, as_of, "
                "license_status, confidence) SELECT entity_id, cik, '0000000000-26-999999', "
                "'10-Q', filing_date, accepted_at, report_date, items, source_id, source_tier, "
                "source_url, :published, published_at_precision, ingested_at, effective_from, "
                "as_of, license_status, confidence FROM filings WHERE id = :id"
            ),
            {"published": VALUED_AT - timedelta(days=1), "id": template.id},
        )
        session.commit()
        rules = stored_alert_rules(session)
        assert rules is not None
        for row in session.scalars(select(ConvergenceAssessment)):
            instrument = session.get_one(Instrument, row.instrument_id)
            assert instrument.entity_id is not None
            assignment = session.get_one(BuybackStateAssignment, row.buyback_assignment_id)
            reading = buyback_reading(
                assignment.id,
                assignment.state,
                assignment.known_at,
                assignment.rule_version,
                assignment.assessment,
            )
            again, _ = convergence_at(
                session,
                rules,
                instrument.id,
                issuer_chain(session, instrument.entity_id).order,
                reading,
                row.known_at,
                row.system_time,
            )
            assert again.model_dump(mode="json") == row.assessment, row.ticker
        # Read now, the late filing is an item of AAPL's window.
        instrument = session.get_one(Instrument, aapl.instrument_id)
        assert instrument.entity_id is not None
        now = session.execute(select(func.now())).scalar_one()
        assignment = session.get_one(BuybackStateAssignment, aapl.buyback_assignment_id)
        later, _ = convergence_at(
            session,
            rules,
            instrument.id,
            issuer_chain(session, instrument.entity_id).order,
            buyback_reading(
                assignment.id, assignment.state, VALUED_AT, "0.3.0", assignment.assessment
            ),
            VALUED_AT,
            now,
        )
        assert "0000000000-26-999999" in {i.source for i in later.items}
        assert "0000000000-26-999999" not in {i["source"] for i in aapl.assessment["items"]}


def test_every_alert_links_its_rule_version_and_evidence(client: TestClient) -> None:
    # Acceptance 1.
    entries = all_alerts(client)
    assert entries
    kinds = {e["kind"] for e in entries}
    assert "event" in kinds
    for entry in entries:
        assert entry["rule_version"] == "0.3.0"
        assert entry["evidence"] and all(e["label"] for e in entry["evidence"])
        for evidence in entry["evidence"]:
            if evidence["table"] in ("filings", "filing_buyback_statements"):
                assert evidence["url"].startswith("https://www.sec.gov/")
        if entry["kind"] == "level_change":
            detail = client.get(f"/alerts/{entry['id']}").json()
            assessment = detail["assessment"]
            # A fall to no level is stored as level 0 on the alert.
            assert (assessment["level"] or 0) == entry["level"]
            cited = {e["id"] for e in entry["evidence"]}
            items = {i["row_id"] for i in assessment["items"]}
            # A fall to no level cites the buyback assignment it read.
            assert cited == items or (not items and len(cited) == 1)
        else:
            assert (entry["level"], entry["level_name"]) == (0, "L0 Information")
    # Event alerts come from the 30 days before each live assessment.
    events = [e for e in entries if e["kind"] == "event"]
    assert all(e["known_at"] <= iso(VALUED_AT) for e in events)
    assert {e["evidence"][0]["table"] for e in events} <= {
        "filings",
        "filing_buyback_statements",
        "buyback_state_assignments",
    }
    # By default only open, live alerts: level changes evaluated later are backfilled.
    default = client.get("/alerts", params={"known_at": iso(VALUED_AT)}).json()
    assert all(not e["backfilled"] for e in default["entries"])
    assert sum(default["open_by_level"].values()) == len(default["entries"])


def test_acknowledging_is_audited_and_happens_once(
    client: TestClient, engine: Engine, stored: datetime
) -> None:
    # Acceptance 2.
    alert = all_alerts(client)[0]
    response = client.post(f"/alerts/{alert['id']}/acknowledge", json={"note": "seen, no action"})
    assert response.status_code == 201, response.text
    ack = response.json()["acknowledgement"]
    assert ack["note"] == "seen, no action"
    assert client.post(f"/alerts/{alert['id']}/acknowledge", json={}).status_code == 409
    assert client.post(f"/alerts/{uuid4()}/acknowledge", json={}).status_code == 404
    with Session(engine) as session:
        audited = session.execute(
            select(AuditLog.actor, AuditLog.action).where(
                AuditLog.object_type == "alert_acknowledgements"
            )
        ).all()
    assert audited == [("web", "insert")]
    now: dict[str, Any] = {"status": "acknowledged", "include_backfilled": True}
    assert [e["id"] for e in client.get("/alerts", params=now).json()["entries"]] == [alert["id"]]
    # As known at VALUED_AT, before the acknowledgement, it was still open.
    then = all_alerts(client, status="open")
    assert alert["id"] in {e["id"] for e in then}
    labels = client.get("/audit-log", params={"table": "alert_acknowledgements"}).json()
    assert labels["entries"][0]["object_label"] == f"acknowledged: {alert['title']}"


def test_alerts_cannot_change_and_levels_stop_at_l4(engine: Engine, stored: datetime) -> None:
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("UPDATE alerts SET title = 'x'"))
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("DELETE FROM alert_acknowledgements"))
    with engine.connect() as conn, pytest.raises(IntegrityError, match="level_range"):
        conn.execute(
            text(
                "INSERT INTO convergence_assessments (instrument_id, ticker, known_at, "
                "system_time, rule_version, level, assessment, backfilled, trigger) SELECT "
                "instrument_id, ticker, known_at - interval '1 day', system_time, rule_version, "
                "5, assessment, backfilled, trigger FROM convergence_assessments LIMIT 1"
            )
        )


def test_each_company_level_as_known_on_a_date(client: TestClient) -> None:
    body = client.get("/convergence", params={"known_at": iso(VALUED_AT)}).json()
    assert body["rule_version"] == "0.3.0"
    companies = {c["ticker"]: c for c in body["companies"]}
    assert sorted(companies) == ["AAPL", "META", "XOM"]
    for company in companies.values():
        assert company["known_at"] == iso(VALUED_AT)
        assert company["levels"][4]["detail"].startswith(("needs L3 first", "standard paper"))
    levels = [c["level"] if c["level"] is not None else -1 for c in body["companies"]]
    assert levels == sorted(levels, reverse=True)
    april = client.get("/convergence", params={"known_at": "2026-04-15T00:00:00Z"}).json()
    assert {c["known_at"] for c in april["companies"]} == {iso(MONTH_END)}
    assert (
        client.get("/convergence", params={"known_at": "2026-01-01T00:00:00Z"}).json()["companies"]
        == []
    )


def test_rule_sets_are_registered_once_and_never_change(engine: Engine) -> None:
    rules = load_alert_rules()
    with Session(engine) as session:
        assert sync_alert_rules(session, rules).unchanged == ["0.3.0", "0.2.0", "0.1.0"]
        entry = rules.rule_sets[0]
        edited = entry.model_copy(update={"event_lookback_days": 60})
        with pytest.raises(AlertRulesVersionError, match=r"0\.3\.0 changed"):
            sync_alert_rules(session, rules.model_copy(update={"rule_sets": [edited]}))
        bumped = edited.model_copy(update={"rule_version": "0.4.0", "status": "retired"})
        result = sync_alert_rules(session, rules.model_copy(update={"rule_sets": [entry, bumped]}))
        assert result.created == ["0.4.0"]
        session.rollback()


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    at = iso(VALUED_AT)
    level = next(e for e in all_alerts(client) if e["kind"] == "level_change")
    recorded: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("alerts", "/alerts", {"known_at": at, "status": "all", "include_backfilled": True}),
        ("alerts-open", "/alerts", {"known_at": at}),
        ("convergence", "/convergence", {"known_at": at}),
        ("alert-detail", f"/alerts/{level['id']}", {}),
    )
    for name, path, params in recorded:
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded SEC filings, Alpaca closes, FRED yields and news replayed "
            "into the integration test database (tests/integration/test_alerts.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
