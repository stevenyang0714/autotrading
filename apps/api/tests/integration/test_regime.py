"""Macro regime (M2.1, ADR-029) over the recorded FRED vintages and Alpaca closes: every input
read as known at (T, S), stored assessments recompute identically after later revisions, the
stress state's market-wide alert, and the rule set's sha guard."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.api.regime import regime as regime_endpoint
from autotrading.config_sync import (
    RegimeRulesVersionError,
    load_macro_series,
    load_sources,
    sync_alert_rules,
    sync_macro_series,
    sync_regime_rules,
    sync_sources,
)
from autotrading.db.models import Alert, RegimeAssessment, Source
from autotrading.domain.provenance import end_of_day
from autotrading.domain.regime import STRESS_ORDER
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.convergence import load_alert_rules
from autotrading.repositories.factors import session_points
from autotrading.repositories.regime import (
    load_regime_rules,
    raise_alerts,
    record_regime,
    regime_at,
    stored_regime_rules,
)
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
VALUED_AT = datetime(2026, 10, 6, 12, tzinfo=UTC)  # the recorded data ends on 2026-10-05
MONTH_END = end_of_day(datetime(2026, 8, 31).date())
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
        sync_regime_rules(session, load_regime_rules())
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
    """Replay every recorded FRED series and the Alpaca closes, then assess the regime at a
    month end and at VALUED_AT as the database holds it now; returns that system time."""
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    runner = IngestionRunner(
        sessions,
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        alpaca_replay.register_recorded(
            fred_replay.register_recorded(recorded_registry()), fixture=False
        ),
    )
    fred_replay.replay(runner, WINDOW)
    alpaca_replay.replay(runner, WINDOW)
    with sessions() as session:
        now = session.execute(select(func.now())).scalar_one()
        rules = stored_regime_rules(session)
        assert rules is not None
        for at in (MONTH_END, VALUED_AT):
            record_regime(session, rules, at, now, "manual")
        session.commit()
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


def assessment(session: Session, at: datetime) -> RegimeAssessment:
    return session.scalars(select(RegimeAssessment).where(RegimeAssessment.known_at == at)).one()


def test_every_dimension_and_flag_reads_inputs_known_then(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        row = assessment(session, VALUED_AT)
    regime = row.assessment
    assert (row.rule_version, row.backfilled) == ("0.2.0", True)  # evaluated after its T
    states = {d["dimension"]: d["state"] for d in regime["dimensions"]}
    assert set(states) == {"growth", "inflation", "policy", "credit", "volatility"}
    assert "unavailable" not in states.values()
    assert regime["stress"] in STRESS_ORDER
    assert row.flags_available == 9  # every flag has its inputs in the recordings
    credit = next(d for d in regime["dimensions"] if d["dimension"] == "credit")
    assert credit["detail"] == "from the high-yield spread"
    inputs = [
        i
        for d in regime["dimensions"]
        for r in d["readings"]
        for i in r["inputs"]
        if i["vintage"] is not None
    ]
    assert inputs and all(i["vintage"] <= "2026-10-06" for i in inputs)
    assert all(i["observation_date"] <= "2026-10-06" for i in inputs)


def test_a_stored_regime_recomputes_identically_after_a_later_revision(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    # Phase 2 exit: "regime reproducible from PIT data". A payrolls value revised before T but
    # recorded after S changes the regime read now, never the stored one.
    with sessions() as session:
        rules = stored_regime_rules(session)
        assert rules is not None
        row = assessment(session, VALUED_AT)
        session.execute(
            text(
                "INSERT INTO macro_observations (series_id, observation_date, value, vintage, "
                "version, supersedes_id, revision_reason, source_id, source_tier, source_url, "
                "published_at, published_at_precision, ingested_at, effective_from, effective_to, "
                "as_of, license_status, confidence) SELECT series_id, observation_date, "
                "value + 500, vintage, version + 1, id, 'correction', source_id, source_tier, "
                "source_url, published_at + interval '1 minute', published_at_precision, "
                "ingested_at, effective_from, effective_to, as_of, license_status, confidence "
                "FROM macro_observations WHERE series_id = 'PAYEMS' AND superseded_at IS NULL "
                "ORDER BY observation_date DESC LIMIT 1"
            )
        )
        session.commit()
        again = regime_at(session, rules, row.known_at, row.system_time)
        assert again.model_dump(mode="json") == row.assessment
        now = session.execute(select(func.now())).scalar_one()
        today = regime_at(session, rules, row.known_at, now)
        growth = next(d for d in today.dimensions if d.dimension == "growth")
        stored_growth = next(d for d in row.assessment["dimensions"] if d["dimension"] == "growth")
        payrolls = next(r for r in growth.readings if r.reading_id == "payrolls_3m")
        stored_payrolls = next(
            r for r in stored_growth["readings"] if r["reading_id"] == "payrolls_3m"
        )
        assert str(payrolls.value) != stored_payrolls["value"]


def test_the_regime_as_known_on_a_date(client: TestClient) -> None:
    body = client.get("/regime", params={"known_at": iso(VALUED_AT)}).json()
    assert body["rule_version"] == "0.2.0"
    assert body["current"]["known_at"] == iso(VALUED_AT)
    assert [p["known_at"] for p in body["history"]] == [iso(MONTH_END), iso(VALUED_AT)]
    september = client.get("/regime", params={"known_at": "2026-09-15T00:00:00Z"}).json()
    assert september["current"]["known_at"] == iso(MONTH_END)
    assert (
        client.get("/regime", params={"known_at": "2026-01-01T00:00:00Z"}).json()["current"] is None
    )
    rules = client.get("/regime/rules").json()
    assert sorted((r["rule_version"], r["status"]) for r in rules) == [
        ("0.1.0", "retired"),
        ("0.2.0", "active"),
    ]


def test_the_history_keeps_each_months_highest_stress(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    # ADR-036 D5: daily assessments, one history point per New York month at its worst
    with sessions() as session:
        session.execute(
            text(
                "INSERT INTO regime_assessments (known_at, system_time, rule_version, stress, "
                "quadrant, flags_on, flags_available, assessment, backfilled, trigger) SELECT "
                "known_at - interval '2 days', system_time, rule_version, 'crisis', quadrant, "
                "flags_on, flags_available, assessment, backfilled, trigger FROM "
                "regime_assessments WHERE known_at = :at"
            ),
            {"at": VALUED_AT},
        )
        out = regime_endpoint(session, VALUED_AT)
        session.rollback()
    october = [p for p in out.history if p.known_at.month == 10]
    assert [(p.known_at, p.stress) for p in october] == [(VALUED_AT - timedelta(days=2), "crisis")]
    assert out.current is not None and out.current.known_at == VALUED_AT
    assert [p.known_at for p in out.history] == sorted(p.known_at for p in out.history)


def test_a_change_of_stress_raises_a_market_alert(
    sessions: sessionmaker[Session], client: TestClient
) -> None:
    later = VALUED_AT + timedelta(hours=6)
    with sessions() as session:
        rules = stored_regime_rules(session)
        assert rules is not None
        now = session.execute(select(func.now())).scalar_one()
        coming = regime_at(session, rules, later, now).stress
        assert coming is not None
        other = next(s for s in STRESS_ORDER if s != coming)
        # A previous assessment in another state, just before `later`.
        session.execute(
            text(
                "INSERT INTO regime_assessments (known_at, system_time, rule_version, stress, "
                "quadrant, flags_on, flags_available, assessment, backfilled, trigger) SELECT "
                "known_at + interval '3 hours', system_time, rule_version, :other, quadrant, "
                "flags_on, flags_available, assessment, backfilled, trigger FROM "
                "regime_assessments WHERE known_at = :at"
            ),
            {"other": other, "at": VALUED_AT},
        )
        stored_id = record_regime(session, rules, later, now, "manual")
        session.commit()
        alert = session.scalars(select(Alert).where(Alert.kind == "regime")).one()
    assert (alert.ticker, alert.instrument_id, alert.rule_version) == (None, None, "0.6.0")
    assert alert.source_key == f"regime:{stored_id}"
    assert (alert.level, alert.previous_level) == (STRESS_ORDER[coming], STRESS_ORDER[other])
    assert alert.title.endswith(f"to {coming.upper()} (was {other.upper()})")
    assert alert.evidence[0]["table"] == "regime_assessments"
    listed = client.get(
        "/alerts", params={"status": "all", "include_backfilled": True, "known_at": iso(later)}
    ).json()["entries"]
    market = next(e for e in listed if e["kind"] == "regime")
    assert (market["ticker"], market["level_name"]) == (None, coming.upper())


def test_a_backfill_raises_its_alerts_afterwards_in_order(sessions: sessionmaker[Session]) -> None:
    # ADR-036 D5: backfill messages run concurrently, so a backfilled assessment raises no
    # alert itself; raise_alerts pairs the stored assessments in order of T afterwards.
    later = VALUED_AT + timedelta(hours=12)
    with sessions() as session:
        rules = stored_regime_rules(session)
        assert rules is not None
        now = session.execute(select(func.now())).scalar_one()
        coming = regime_at(session, rules, later, now).stress
        assert coming is not None
        other = next(s for s in STRESS_ORDER if s != coming)
        session.execute(
            text(
                "INSERT INTO regime_assessments (known_at, system_time, rule_version, stress, "
                "quadrant, flags_on, flags_available, assessment, backfilled, trigger) SELECT "
                "known_at + interval '11 hours', system_time, rule_version, :other, quadrant, "
                "flags_on, flags_available, assessment, backfilled, trigger FROM "
                "regime_assessments WHERE known_at = :at"
            ),
            {"other": other, "at": VALUED_AT},
        )
        stored_id = record_regime(session, rules, later, now, "backfill")
        assert stored_id is not None
        source = f"regime:{stored_id}"
        assert session.scalars(select(Alert).where(Alert.source_key == source)).first() is None
        assert raise_alerts(session, rules, now) >= 1
        alert = session.scalars(select(Alert).where(Alert.source_key == source)).one()
        assert (alert.previous_level, alert.level) == (STRESS_ORDER[other], STRESS_ORDER[coming])
        assert alert.backfilled
        session.rollback()


def test_the_backfill_points_are_session_closes_and_month_ends(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    # ADR-036 D5: every session SPY closed, plus month ends (the factor backfill's points)
    with sessions() as session:
        points = session_points(session, "SPY", datetime(2026, 9, 1).date(), stored)
        closes = session.execute(
            text(
                "SELECT DISTINCT bar_date FROM price_bars WHERE symbol = 'SPY' "
                "AND adjustment = 'raw' AND bar_date >= '2026-09-01'"
            )
        ).scalars()
        expected = {end_of_day(d) for d in closes} | {end_of_day(datetime(2026, 9, 30).date())}
    assert points == sorted(expected)
    assert all(p <= stored for p in points)


def test_rule_sets_are_registered_once_and_never_change(engine: Engine) -> None:
    rules = load_regime_rules()
    with Session(engine) as session:
        assert sync_regime_rules(session, rules).unchanged == ["0.2.0", "0.1.0"]
        entry = rules.rule_sets[0]
        edited = entry.model_copy(
            update={"stress": entry.stress.model_copy(update={"elevated_flags": 3})}
        )
        with pytest.raises(RegimeRulesVersionError, match=r"0\.2\.0 changed"):
            sync_regime_rules(session, rules.model_copy(update={"rule_sets": [edited]}))
        session.rollback()


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    recorded: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("regime", "/regime", {"known_at": iso(VALUED_AT)}),
        ("regime-earlier", "/regime", {"known_at": "2026-09-15T00:00:00Z"}),
        (
            "alerts-regime",
            "/alerts",
            {
                "status": "all",
                "include_backfilled": True,
                "known_at": iso(VALUED_AT + timedelta(hours=6)),
            },
        ),
    )
    for name, path, params in recorded:
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded FRED vintages and Alpaca closes replayed into the "
            "integration test database (tests/integration/test_regime.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
