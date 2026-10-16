"""S3 ETF rotation (M2.4, ADR-032) over the recorded FRED vintages and Alpaca closes: the regime
and factor snapshots read as known at (T, S), targets set at month starts and carried within a
month, S3 signals beside other strategies, stored assessments recompute identically, the
rotation API, and the rule set's sha guard."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.config_sync import (
    RotationRulesVersionError,
    load_macro_series,
    load_sources,
    sync_alert_rules,
    sync_factor_definitions,
    sync_macro_series,
    sync_regime_rules,
    sync_rotation_rules,
    sync_sources,
)
from autotrading.db.models import Alert, RotationAssessment, SignalRecord, Source
from autotrading.domain.provenance import end_of_day
from autotrading.domain.rotation import Rotation
from autotrading.domain.signals import SignalIn
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.convergence import load_alert_rules
from autotrading.repositories.factors import (
    load_factor_definitions,
    record_universe,
    stored_definitions,
)
from autotrading.repositories.prices import instruments_by_symbol
from autotrading.repositories.regime import (
    load_regime_rules,
    record_regime,
    stored_regime_rules,
)
from autotrading.repositories.regime import raise_alerts as regime_raise_alerts
from autotrading.repositories.rotation import (
    load_rotation_rules,
    raise_alerts,
    recompute,
    record_points,
    record_rotation,
    rotation_at,
    same,
    stored_rotation_rules,
)
from autotrading.repositories.signals import record_signal
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
VALUED_AT = datetime(2026, 10, 6, 12, tzinfo=UTC)  # the recorded data ends on 2026-10-05
MID_SEPTEMBER = end_of_day(date(2026, 9, 15))
POINTS = [
    end_of_day(date(2026, 7, 31)),
    end_of_day(date(2026, 8, 31)),
    MID_SEPTEMBER,
    end_of_day(date(2026, 9, 30)),
    VALUED_AT,
]
CONFIG = get_settings().resolved_config_dir()
ETFS = ["SPY", "QQQ", "IWM", "XLK", "XLE", "TLT", "IEF", "GLD"]


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
        sync_factor_definitions(session, load_factor_definitions())
        sync_alert_rules(session, load_alert_rules())
        sync_rotation_rules(session, load_rotation_rules())
        for source in session.scalars(select(Source)):
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


@pytest.fixture(scope="module")
def stored(sessions: sessionmaker[Session]) -> Iterator[tuple[datetime, datetime]]:
    """Replay the recorded FRED series and Alpaca closes, store the regime and the ETFs' factor
    snapshots at POINTS, then the rotation at POINTS in order. Returns (the system time before
    the regime and snapshots were stored, the system time of the rotation)."""
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
        before = session.execute(select(func.now())).scalar_one()
        session.commit()
    with sessions() as session:
        regime_rules = stored_regime_rules(session)
        definitions = stored_definitions(session)
        assert regime_rules is not None and definitions is not None
        for at in POINTS:
            record_regime(session, regime_rules, at, before, "manual")
        session.commit()
        record_universe(
            session, definitions, [(at, "price") for at in POINTS], before, "manual", ETFS
        )
    with sessions() as session:
        now = session.execute(select(func.now())).scalar_one()
        rules = stored_rotation_rules(session)
        assert rules is not None
        record_points(session, rules, POINTS, now, "manual")
    yield before, now
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def client(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> Iterator[TestClient]:
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        yield client


def iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def rows(session: Session) -> list[RotationAssessment]:
    return list(
        session.scalars(select(RotationAssessment).order_by(RotationAssessment.known_at)).all()
    )


def test_targets_are_set_at_month_starts_and_carried_within_a_month(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    with sessions() as session:
        found = rows(session)
    assert [r.known_at for r in found] == POINTS
    assert [r.reason for r in found] == [
        "month_start",
        "month_start",
        "month_start",
        "carried",
        "month_start",
    ]
    july, august, september, end, october = found
    assert (july.previous_id, august.previous_id) == (None, july.id)
    assert end.previous_id == september.id and end.target == september.target
    assert all(r.backfilled and r.trigger == "manual" for r in found)
    current = Rotation.model_validate(october.assessment)
    assert current.stress is not None and current.regime_id is not None
    by = {r.symbol: r for r in current.readings}
    assert list(by) == ETFS
    # SPY and TLT have closes from 2023 (the regime's inputs); the other ETFs one year only,
    # too short for 12-1 momentum: they are not selected, with the reason.
    assert by["QQQ"].trend[0].status == "unavailable" and not by["QQQ"].eligible
    assert by["SPY"].trend[0].status in ("pass", "fail")
    assert set(october.target or {}) <= {"SPY", "TLT"}


def test_inputs_are_read_as_the_database_held_them(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    before, now = stored
    with sessions() as session:
        rules = stored_rotation_rules(session)
        assert rules is not None
        earlier = rotation_at(session, rules, VALUED_AT, before, None)
        later = rotation_at(session, rules, VALUED_AT, now, None)
    assert earlier.reason == "unavailable" and earlier.detail == "no regime assessment known at T"
    assert earlier.target is None
    assert later.reason == "month_start" and later.target is not None


def test_every_stored_assessment_recomputes_identically(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    with sessions() as session:
        for row in rows(session):
            again = recompute(session, row)
            assert again is not None and same(row, again), row.known_at


def test_a_new_target_makes_s3_signals_beside_other_strategies(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    with sessions() as session:
        found = session.scalars(select(SignalRecord).where(SignalRecord.strategy_id == "S3")).all()
        targets = [r for r in rows(session) if r.rebalance]
        expected = sum(2 * len(r.target or {}) for r in targets)
        assert len(found) == expected
        assert {s.family_id for s in found} <= {1, 5}
        assert all(s.direction == "long" and s.execution_eligibility == "paper_only" for s in found)
        # The strategy is part of the key (NULLS NOT DISTINCT): another strategy's family 5
        # signal on SPY at the same T and version is a new row; the same one twice is not.
        spy = instruments_by_symbol(session, ["SPY"])["SPY"]
        base = SignalIn(
            family_id=5,
            strategy_id=None,
            rule_version="0.1.0",
            score=None,
            direction="long",
            generated_at=VALUED_AT,
            valid_from=VALUED_AT,
            system_time=VALUED_AT,
            observation_ids=[{"table": "factor_snapshots", "id": "x"}],
            source_quality=1,
            evidence_independence=1,
            execution_eligibility="paper_only",
            backfilled=False,
        )
        assert record_signal(session, spy, "SPY", base) is not None
        assert record_signal(session, spy, "SPY", base) is None
        session.rollback()


def test_target_changes_raise_alerts_once(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    _, now = stored
    with sessions() as session:
        rules = stored_rotation_rules(session)
        assert rules is not None
        alerts = session.scalars(select(Alert).where(Alert.kind == "rotation")).all()
        assert all(a.rule_version == "0.4.0" and a.ticker is None for a in alerts)
        assert all(a.evidence[0]["table"] == "rotation_assessments" for a in alerts)
        changed = [
            r
            for r in rows(session)
            if r.rebalance
            and r.previous_id is not None
            and r.target != session.get(RotationAssessment, r.previous_id).target  # type: ignore[union-attr]
        ]
        assert len(alerts) == len(changed)
        assert raise_alerts(session, rules, now) == 0  # already raised: nothing new
        session.rollback()


def test_the_rotation_api(client: TestClient, stored: tuple[datetime, datetime]) -> None:
    body = client.get("/rotation", params={"known_at": iso(VALUED_AT)}).json()
    assert body["rule_version"] == "0.1.0"
    assert body["detail"].startswith("Research only (paper)")
    assert body["current"]["known_at"] == iso(VALUED_AT)
    assert [p["reason"] for p in body["history"]] == ["month_start"] * 4
    assert all(Decimal(p["cash_pct"]) >= 0 for p in body["history"])
    earlier = client.get("/rotation", params={"known_at": iso(MID_SEPTEMBER)}).json()
    assert earlier["current"]["known_at"] == iso(MID_SEPTEMBER)
    assert len(earlier["history"]) == 3
    rules = client.get("/rotation/rules").json()
    assert [(r["rule_version"], r["status"]) for r in rules] == [("0.1.0", "active")]


def test_a_changed_released_rule_set_is_refused(engine: Engine) -> None:
    file = load_rotation_rules()
    entry = file.rule_sets[0]
    edited = entry.model_copy(update={"weight_quantum_pct": Decimal("0.1")})
    with Session(engine) as session:
        with pytest.raises(RotationRulesVersionError):
            sync_rotation_rules(session, file.model_copy(update={"rule_sets": [edited]}))
        session.rollback()


def test_signals_list_the_target_in_force(
    client: TestClient, sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    with sessions() as session:
        october = rows(session)[-1]
    target = october.target or {}
    body = client.get("/signals", params={"known_at": iso(VALUED_AT), "strategy": "S3"}).json()
    assert body["rule_versions"] == {"S1": "0.3.0", "S3": "0.1.0"}
    current = body["current"]
    assert len(current) == 2 * len(target)
    for signal in current:
        assert (signal["strategy_id"], signal["state"]) == ("S3", "rotation_target")
        assert signal["family_id"] in (1, 5) and signal["generated_at"] == iso(VALUED_AT)
        assert Decimal(signal["weight_pct"]) == Decimal(target[signal["ticker"]])
        assert signal["stress"] == october.stress
    both = client.get("/signals", params={"known_at": iso(VALUED_AT)}).json()
    assert [s for s in both["current"] if s["strategy_id"] == "S3"] == current
    history = client.get(
        "/signals", params={"known_at": iso(VALUED_AT), "ticker": "SPY", "strategy": "S3"}
    ).json()["history"]
    times = [s["generated_at"] for s in history]
    assert times == sorted(times, reverse=True)
    assert all(s["ticker"] == "SPY" for s in history)


def test_candidates_list_the_rotation_target_with_its_context(
    client: TestClient, sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    with sessions() as session:
        october = rows(session)[-1]
    body = client.get("/candidates", params={"known_at": iso(VALUED_AT)}).json()
    assert body["detail"].startswith("Long only (no short data, OD-5)")
    assert body["companies"] == []  # no convergence assessment in this module
    assert [e["ticker"] for e in body["etfs"]] == list(october.target or {})
    for etf in body["etfs"]:
        assert (etf["strategy_id"], etf["rotation_rule_version"]) == ("S3", "0.1.0")
        assert (etf["regime_rule_version"], etf["factor_definition_version"]) == ("0.1.0", "0.1.0")
        assert etf["reading"]["symbol"] == etf["ticker"] and etf["reading"]["eligible"]
    assert body["context"]["stress"] == october.stress
    before = client.get("/candidates", params={"known_at": "2026-07-01T00:00:00Z"}).json()
    assert before["etfs"] == [] and before["context"] is None


def test_the_market_alerts_are_raised_once(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    _, now = stored
    with sessions() as session:
        regime_rules = stored_regime_rules(session)
        assert regime_rules is not None
        assert regime_raise_alerts(session, regime_rules, now) == 0  # raised when stored
        session.rollback()


def test_rotation_alerts_are_listed_with_the_market_alerts(
    client: TestClient, sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    with sessions() as session:
        stored_count = len(session.scalars(select(Alert).where(Alert.kind == "rotation")).all())
    body = client.get(
        "/alerts",
        params={"known_at": iso(VALUED_AT), "status": "all", "include_backfilled": True},
    ).json()
    rotation = [e for e in body["entries"] if e["kind"] == "rotation"]
    assert len(rotation) == stored_count
    for entry in rotation:
        assert (entry["ticker"], entry["level_name"]) == (None, "S3 TARGET")
        assert entry["title"].startswith("S3 rotation (")
        assert entry["evidence"][0]["table"] == "rotation_assessments"


def test_an_unavailable_assessment_is_stored_without_a_target(
    sessions: sessionmaker[Session], stored: tuple[datetime, datetime]
) -> None:
    before, _ = stored
    early = end_of_day(date(2026, 6, 30))  # no regime recorded by `before`
    with sessions() as session:
        rules = stored_rotation_rules(session)
        assert rules is not None
        row = record_rotation(session, rules, early, before, "manual")
        assert row is not None
        assert (row.reason, row.target, row.rebalance) == ("unavailable", None, False)
        signals = select(SignalRecord).where(SignalRecord.generated_at == early)
        assert session.scalars(signals).all() == []
        session.rollback()


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    at = iso(VALUED_AT)
    recorded: tuple[tuple[str, str, Any], ...] = (
        ("rotation", "/rotation", {"known_at": at}),
        ("rotation-earlier", "/rotation", {"known_at": "2026-07-01T00:00:00Z"}),
        ("candidates", "/candidates", {"known_at": at}),
        ("signals-rotation", "/signals", {"known_at": at, "strategy": "S3"}),
    )
    for name, path, params in recorded:
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded FRED vintages and Alpaca closes replayed into the "
            "integration test database (tests/integration/test_rotation.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
