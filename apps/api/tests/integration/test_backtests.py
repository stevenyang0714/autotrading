"""Backtests (M2.5, ADR-033) over the recorded FRED vintages and Alpaca closes: stored runs
recompute identically, a later close, revision or snapshot never changes a stored run
(look-ahead), performance is withheld by the database too, the monthly schedule, and the API."""

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.config_sync import (
    BacktestRulesVersionError,
    load_backtest_rules,
    load_macro_series,
    load_momentum_rules,
    load_sources,
    sync_alert_rules,
    sync_backtest_rules,
    sync_factor_definitions,
    sync_macro_series,
    sync_momentum_rules,
    sync_regime_rules,
    sync_risk_rules,
    sync_rotation_rules,
    sync_sources,
)
from autotrading.db.models import BacktestRun, PriceBar, Source
from autotrading.domain.provenance import Provenance, end_of_day
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.backtest import (
    ran_this_month,
    recompute,
    record_all,
    same,
    stored_backtest_rules,
)
from autotrading.repositories.convergence import load_alert_rules
from autotrading.repositories.factors import (
    load_factor_definitions,
    record_universe,
    stored_definitions,
)
from autotrading.repositories.prices import BarIn, PriceRepository
from autotrading.repositories.regime import load_regime_rules, record_regime, stored_regime_rules
from autotrading.repositories.risk import load_risk_rules
from autotrading.repositories.rotation import (
    load_rotation_rules,
    record_points,
    stored_rotation_rules,
)
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
VALUED_AT = datetime(2026, 10, 6, 12, tzinfo=UTC)  # the recorded data ends on 2026-10-05
POINTS = [end_of_day(date(2026, m, d)) for m, d in ((7, 31), (8, 31), (9, 30))] + [VALUED_AT]
CONFIG = get_settings().resolved_config_dir()
SYMBOLS = ["SPY", "QQQ", "IWM", "XLK", "XLE", "TLT", "IEF", "GLD", "AAPL", "MSFT", "NVDA"]


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
        sync_risk_rules(session, load_risk_rules())
        sync_rotation_rules(session, load_rotation_rules())
        sync_momentum_rules(session, load_momentum_rules(CONFIG / "momentum_rules.yaml"))
        sync_backtest_rules(session, load_backtest_rules(CONFIG / "backtest_rules.yaml"))
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
    """Replay the recorded FRED series and Alpaca closes; store the regime, the full factor
    snapshots and the rotation at POINTS; then every strategy's backtest at VALUED_AT. Returns
    the backtests' system time."""
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
        regime_rules = stored_regime_rules(session)
        definitions = stored_definitions(session)
        assert regime_rules is not None and definitions is not None
        for at in POINTS:
            record_regime(session, regime_rules, at, now, "manual")
        session.commit()
        record_universe(
            session, definitions, [(at, "all") for at in POINTS], now, "manual", SYMBOLS
        )
    with sessions() as session:
        held = session.execute(select(func.now())).scalar_one()
        rotation = stored_rotation_rules(session)
        assert rotation is not None
        record_points(session, rotation, POINTS, held, "manual")
    with sessions() as session:
        ran = session.execute(select(func.now())).scalar_one()
        rules = stored_backtest_rules(session)
        assert rules is not None
        record_all(session, rules, VALUED_AT, ran, "manual")
    yield ran
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def client(sessions: sessionmaker[Session], stored: datetime) -> Iterator[TestClient]:
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        yield client


def iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def runs(session: Session) -> list[BacktestRun]:
    return list(session.scalars(select(BacktestRun).order_by(BacktestRun.strategy_id)).all())


def provenance_of(bar: PriceBar, published_at: datetime) -> Provenance:
    return Provenance(
        source_id=bar.source_id,
        source_tier=bar.source_tier,
        source_url=bar.source_url,
        published_at=published_at,
        published_at_precision="exact",
        ingested_at=datetime.now(UTC),
        effective_from=bar.effective_from,
        effective_to=bar.effective_to,
        as_of=bar.as_of,
        license_status=bar.license_status,  # type: ignore[arg-type]
        confidence=float(bar.confidence),
        source_timezone=bar.source_timezone,
    )


def revised(bar: PriceBar, published_at: datetime) -> BarIn:
    """The same session's close, corrected later."""
    return BarIn(
        instrument_id=bar.instrument_id,
        symbol=bar.symbol,
        adjustment=bar.adjustment,
        bar_time=bar.bar_time,
        open=bar.open,
        high=bar.high + 5,
        low=bar.low,
        close=bar.close + 5,
        volume=bar.volume,
        vwap=bar.vwap,
        trade_count=bar.trade_count,
        feed=bar.feed,
        feed_status=bar.feed_status,
        provenance=provenance_of(bar, published_at),
    )


def test_every_strategy_has_a_stored_run_without_performance(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        found = runs(session)
    assert [(r.strategy_id, r.known_at, r.trigger) for r in found] == [
        ("S1", VALUED_AT, "manual"),
        ("S3", VALUED_AT, "manual"),
        ("S4", VALUED_AT, "manual"),
    ]
    for row in found:
        assert row.performance_reported is False
        assert all(w["value"] is None for w in row.document["withheld"])
        for trade in row.document["trades"]:
            # filled after the target was known: never the close of the signal's own day
            assert date.fromisoformat(trade["day"]) > POINTS[0].date()
    s3 = next(r for r in found if r.strategy_id == "S3")
    # S3 targets were set at the month ends: each fills at the next session close
    fills = [
        (datetime.fromisoformat(r["at"]), date.fromisoformat(r["fill_day"]))
        for r in s3.document["rebalances"]
        if r["fill_day"]
    ]
    assert fills and all(day > at.astimezone(UTC).date() - timedelta(days=1) for at, day in fills)
    assert all(end_of_day(day) > at for at, day in fills)


def test_every_stored_run_recomputes_identically(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        for row in runs(session):
            again = recompute(session, row)
            assert again is not None and same(row, again), row.strategy_id


def test_a_later_close_revision_or_snapshot_never_changes_a_stored_run(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        spy = session.scalars(
            select(PriceBar).where(
                PriceBar.symbol == "SPY",
                PriceBar.adjustment == "raw",
                PriceBar.bar_date == date(2026, 9, 2),
            )
        ).one()
        # a corrected close published a minute later (recorded after the runs' S), and the
        # regime and snapshots assessed again later: none was held at S
        PriceRepository(session).insert_bars(
            [revised(spy, spy.published_at + timedelta(minutes=1))], actor="test:ingest"
        )
        session.commit()
        later = session.execute(select(func.now())).scalar_one()
        regime_rules = stored_regime_rules(session)
        definitions = stored_definitions(session)
        assert regime_rules is not None and definitions is not None
        record_regime(session, regime_rules, end_of_day(date(2026, 9, 15)), later, "manual")
        session.commit()
        record_universe(
            session, definitions, [(end_of_day(date(2026, 9, 15)), "all")], later, "manual", SYMBOLS
        )
        for row in runs(session):
            again = recompute(session, row)
            assert again is not None and same(row, again), row.strategy_id


def test_the_database_refuses_reported_performance(engine: Engine, stored: datetime) -> None:
    with engine.connect() as conn, pytest.raises(IntegrityError, match="performance_withheld"):
        conn.execute(
            text(
                "INSERT INTO backtest_runs (known_at, system_time, rule_version, strategy_id, "
                "strategy_rule_version, trigger, performance_reported, document) VALUES "
                "(now(), now(), '0.1.0', 'S3', '0.1.0', 'manual', true, '{}')"
            )
        )


def test_the_schedule_runs_once_a_month(sessions: sessionmaker[Session], stored: datetime) -> None:
    with sessions() as session:
        rules = stored_backtest_rules(session)
        assert rules is not None
        assert ran_this_month(session, rules, datetime(2026, 10, 20, tzinfo=UTC))
        assert not ran_this_month(session, rules, datetime(2026, 11, 2, tzinfo=UTC))
        assert not ran_this_month(session, rules, datetime(2026, 9, 30, tzinfo=UTC))


def test_the_backtests_api(client: TestClient, stored: datetime) -> None:
    body = client.get("/backtests", params={"known_at": iso(VALUED_AT)}).json()
    assert body["rule_version"] == "0.1.0"
    assert body["detail"].startswith("Backtests on stored point-in-time data")
    assert "Performance is withheld (OD-7)" in body["detail"]
    assert [r["run"]["strategy_id"] for r in body["runs"]] == ["S1", "S3", "S4"]
    for stored_run in body["runs"]:
        run = stored_run["run"]
        assert stored_run["performance_reported"] is False
        assert [s["scenario"] for s in run["scenarios"]] == ["base", "double"]
        assert run["cost_bps"] == {"equity": "7", "etf": "3"}
    overlap = body["overlap"]
    assert [s["strategy_id"] for s in overlap["strategies"]] == ["S1", "S3", "S4"]
    one = client.get(f"/backtests/{body['runs'][1]['id']}").json()
    assert one["run"]["strategy_id"] == "S3"
    assert client.get(f"/backtests/{uuid4()}").status_code == 404
    assert (
        client.get("/backtests", params={"known_at": "2026-09-01T00:00:00Z"}).json()["runs"] == []
    )
    rules = client.get("/backtests/rules").json()
    assert [(r["rule_version"], r["status"]) for r in rules] == [("0.1.0", "active")]
    momentum = client.get("/momentum/rules").json()
    assert momentum[0]["content"]["universe"][0] == "AAPL"


def test_a_changed_released_rule_set_is_refused(engine: Engine) -> None:
    file = load_backtest_rules(CONFIG / "backtest_rules.yaml")
    edited = file.rule_sets[0].model_copy(update={"benchmark": "QQQ"})
    with Session(engine) as session:
        with pytest.raises(BacktestRulesVersionError):
            sync_backtest_rules(session, file.model_copy(update={"rule_sets": [edited]}))
        session.rollback()


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    response = client.get("/backtests", params={"known_at": iso(VALUED_AT)})
    assert response.status_code == 200
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "recorded_from": "recorded FRED vintages and Alpaca closes replayed into the "
        "integration test database (tests/integration/test_backtests.py)",
        "endpoint": "/backtests",
        "params": {"known_at": iso(VALUED_AT)},
        "response": response.json(),
    }
    (target / "backtests.json").write_text(json.dumps(record, indent=2) + "\n")
