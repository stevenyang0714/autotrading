"""Price, trend and factors (M2.2, ADR-030) over the recorded SEC facts, Alpaca closes, splits
and dividends: every input read as known at (T, S), stored snapshots recompute identically,
NVDA's 2024 split leaves the measures continuous, a later dividend does not change a stored
snapshot, ETFs have price measures only, and the definition set's sha guard."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.alpaca.refresh import universe
from autotrading.adapters.sec.refresh import universe_predecessors
from autotrading.adapters.sec.tickers import SecTickersJob
from autotrading.config_sync import (
    FactorDefinitionsVersionError,
    load_sources,
    sync_factor_definitions,
    sync_sources,
)
from autotrading.db.models import DividendEvent, FactorSnapshot, PriceBar, Source
from autotrading.domain.fair_value import month_ends
from autotrading.domain.provenance import end_of_day
from autotrading.domain.splits import effective_at
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.factors import (
    backfill_points,
    load_factor_definitions,
    recompute,
    record_universe,
    same,
    snapshot_at,
    stored_definitions,
    targets,
)
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry, replay

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
VALUED_AT = datetime(2026, 10, 6, 12, tzinfo=UTC)  # the recorded closes end on 2026-10-05
SPLIT_SESSION = end_of_day(date(2024, 6, 7))  # NVDA's last close before its 10-for-1 split
AFTER_SPLIT = end_of_day(date(2024, 6, 30))
HISTORY = ("NVDA", "SPY", "AAPL")  # recorded from 2023-05 (NVDA, SPY) or with facts (AAPL)
CONFIG = get_settings().resolved_config_dir()
Point = tuple[datetime, Literal["price", "all"]]


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
        sync_factor_definitions(session, load_factor_definitions())
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
    """Replay the recorded SEC and Alpaca data, then store snapshots: every instrument at the
    month ends since 2025-11 and at VALUED_AT; NVDA, SPY and AAPL also at the month ends since
    2024-01 and at NVDA's last session before its split. Returns the system time."""
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
    # Every universe equity's instrument (the recorded facts cover AAPL, META and XOM only).
    symbols, etfs = universe(CONFIG)
    runner.execute(
        runner.create_run(
            SecTickersJob.name,
            {"tickers": [s for s in symbols if s not in etfs], "predecessors": {}},
            WINDOW,
        )
    )
    replay(
        runner,
        WINDOW,
        universe_predecessors(CONFIG),
        before_instances=lambda: alpaca_replay.replay_splits(runner, WINDOW),
    )
    alpaca_replay.replay(runner, WINDOW)
    with sessions() as session:
        now = session.execute(select(func.now())).scalar_one()
        definitions = stored_definitions(session)
        assert definitions is not None
        recent: list[Point] = [(at, "all") for at in month_ends(date(2025, 11, 1), VALUED_AT)]
        record_universe(session, definitions, [*recent, (VALUED_AT, "all")], now, "manual")
        earlier: list[Point] = [
            (at, "all") for at in month_ends(date(2024, 1, 1), datetime(2025, 10, 31, tzinfo=UTC))
        ]
        record_universe(
            session,
            definitions,
            [*earlier, (SPLIT_SESSION, "price")],
            now,
            "manual",
            symbols=HISTORY,
        )
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


def snapshot(session: Session, symbol: str, at: datetime) -> FactorSnapshot:
    return session.scalars(
        select(FactorSnapshot).where(FactorSnapshot.symbol == symbol, FactorSnapshot.known_at == at)
    ).one()


def measures(row: FactorSnapshot) -> dict[str, dict[str, Any]]:
    return {m["measure_id"]: m for m in row.snapshot["measures"]}


def test_every_stored_snapshot_recomputes_identically(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        rows = session.scalars(select(FactorSnapshot)).all()
        assert len(rows) > 200
        assert all(same(row, recompute(session, row)) for row in rows)
        row = snapshot(session, "NVDA", VALUED_AT)
    assert (row.definition_version, row.backfilled, row.scope) == ("0.1.0", True, "all")
    assert row.last_close == date(2026, 10, 5)
    assert row.measure_values == {m["measure_id"]: m["value"] for m in row.snapshot["measures"]}


def test_nvda_across_its_split_reads_closes_on_the_basis_of_the_date(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        before = measures(snapshot(session, "NVDA", SPLIT_SESSION))
        after = measures(snapshot(session, "NVDA", AFTER_SPLIT))
        split_closes = {
            bar.bar_date: bar.close
            for bar in session.scalars(
                select(PriceBar).where(
                    PriceBar.symbol == "NVDA",
                    PriceBar.adjustment == "split",
                    PriceBar.superseded_at.is_(None),
                )
            )
        }
    # Before the split the closes are on the old basis: 2024-06-07 closed at 1208.88.
    last_before = before["close_vs_sma_50"]["inputs"][0]
    assert (last_before["end"], Decimal(last_before["value"])) == ("2024-06-07", Decimal("1208.88"))
    # After it, every close is on the new one, as Alpaca's split-adjusted closes are.
    for item in after["momentum_12_1"]["inputs"][:2]:
        day = date.fromisoformat(item["end"])
        assert abs(Decimal(item["value"]) - split_closes[day]) <= Decimal("0.01")
    average = after["close_vs_sma_50"]["inputs"][1]
    window = sorted(d for d in split_closes if date(2024, 4, 1) <= d <= date(2024, 6, 28))[-50:]
    expected = sum((split_closes[d] for d in window), Decimal(0)) / 50
    assert abs(Decimal(average["value"]) - expected) <= Decimal("0.01")
    # The 12-1 momentum is a 12-month total return, defined across the split.
    assert Decimal(after["momentum_12_1"]["value"]) > 100
    assert before["momentum_12_1"]["value"] is not None


def test_a_dividend_recorded_later_does_not_change_a_stored_snapshot(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        row = snapshot(session, "NVDA", AFTER_SPLIT)
        nvda = targets(session, ["NVDA"])[0]
        source = session.get_one(Source, "alpaca_iex")
        ex = date(2024, 6, 20)
        session.add(
            DividendEvent(
                instrument_id=nvda.instrument.id,
                symbol="NVDA",
                ex_date=ex,
                rate=Decimal("5"),
                special=True,
                foreign=False,
                source_id=source.id,
                source_tier=source.tier,
                source_url="https://data.alpaca.markets/v1/corporate-actions?test=1",
                published_at=effective_at(ex),
                published_at_precision="day",
                ingested_at=datetime.now(UTC),
                effective_from=effective_at(ex),
                as_of=effective_at(ex),
                license_status=source.license_status,
                confidence=Decimal(1),
            )
        )
        session.flush()
        assert same(row, recompute(session, row))  # recorded after S: not part of it
        stored_reversal = Decimal(measures(row)["reversal_1m"]["value"])
        definitions = stored_definitions(session)
        assert definitions is not None
        later = session.execute(select(func.now())).scalar_one() + timedelta(seconds=1)
        again = snapshot_at(session, definitions, nvda, AFTER_SPLIT, later, "all")
        session.rollback()
    reversal = {m.measure_id: m for m in again.measures}["reversal_1m"]
    assert reversal.value is not None and reversal.value > stored_reversal


def test_etfs_have_price_and_relative_measures_only(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        tlt = snapshot(session, "TLT", VALUED_AT)
        spy = snapshot(session, "SPY", VALUED_AT)
        aapl = snapshot(session, "AAPL", VALUED_AT)
    groups = {m["group"] for m in tlt.snapshot["measures"]}
    assert groups == {"trend", "risk", "relative"}
    assert tlt.snapshot["instrument_type"] == "etf"
    assert {m["group"] for m in aapl.snapshot["measures"]} >= {"value", "quality"}
    assert measures(spy)["relative_momentum_12_1"]["reason"] == "not_meaningful"
    # TLT pays monthly: its reversal to the end of September reinvests the 09-01 dividend.
    with sessions() as session:
        september = snapshot(session, "TLT", end_of_day(date(2026, 9, 30)))
    reversal = measures(september)["reversal_1m"]["inputs"]
    dividends = next(i for i in reversal if i["name"] == "dividends")
    assert Decimal(dividends["value"]) > 0


def test_instrument_factors_as_known_on_a_date(client: TestClient) -> None:
    response = client.get("/instruments/NVDA/factors", params={"known_at": "2024-06-20T00:00:00Z"})
    assert response.status_code == 200
    body = response.json()
    assert body["instrument_type"] == "equity"
    # the latest snapshot at or before T: the session before the split, never a later one
    assert body["price"]["known_at"].startswith("2024-06-08")
    assert body["fundamentals"]["known_at"].startswith("2024-06-01")  # the May month end
    by = {m["measure_id"]: m for m in body["measures"]}
    # the last snapshot of each month known then: the month ends since 2024-01 and June's
    # session before the split (12-1 momentum needs a year of closes first)
    assert by["close_vs_sma_50"]["observations"] == 6
    assert 0 <= Decimal(by["close_vs_sma_50"]["percentile"]) <= 100
    assert all(p["known_at"] <= "2024-06-20" for p in body["history"])


def test_factors_table_and_definitions(client: TestClient) -> None:
    table = client.get("/factors", params={"known_at": iso(VALUED_AT)}).json()
    assert table["benchmark"] == "SPY"
    assert [r["ticker"] for r in table["rows"]][:3] == ["AAPL", "MSFT", "GOOGL"]
    assert len(table["rows"]) == 18
    etf = next(r for r in table["rows"] if r["ticker"] == "TLT")
    assert etf["fundamentals"] is None
    assert {v["group"] for v in etf["values"]} == {"trend", "risk", "relative"}
    definitions = client.get("/factors/definitions").json()
    # one active set per market (M3.7, M3.7b): 0.3.0 for Taiwan (0.2.0 retired), 0.1.0 for the US
    assert [(d["definition_version"], d["status"]) for d in definitions] == [
        ("0.3.0", "active"),
        ("0.2.0", "retired"),
        ("0.1.0", "active"),
    ]
    assert client.get("/instruments/ZZZZ/factors").status_code == 404


def test_backfill_points_are_every_session_and_every_month_end_once(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        definitions = stored_definitions(session)
        assert definitions is not None
        points = backfill_points(session, definitions, 2024, stored)
    scopes = dict(points)
    assert len(scopes) == len(points)  # each T once
    # 2024-12-31 is a session and the year's last month end (2025-01-01 in UTC): all measures
    assert scopes[end_of_day(date(2024, 12, 31))] == "all"
    assert scopes[end_of_day(date(2024, 6, 7))] == "price"
    assert scopes[end_of_day(date(2024, 6, 30))] == "all"  # a Sunday month end
    assert sum(scope == "all" for _, scope in points) == 12
    assert all(p.astimezone(UTC) <= stored for p, _ in points)


def test_a_stale_close_leaves_measures_unavailable_and_the_benchmark_itself_not_meaningful(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    """As CI sees it on a later day: the recorded closes end on 2026-10-05."""
    later = VALUED_AT + timedelta(days=8)
    with sessions() as session:
        definitions = stored_definitions(session)
        assert definitions is not None
        found = {t.symbol: t for t in targets(session, ["SPY", "TLT"])}
        now = session.execute(select(func.now())).scalar_one()
        spy = snapshot_at(session, definitions, found["SPY"], later, now, "price")
        tlt = snapshot_at(session, definitions, found["TLT"], later, now, "price")
    by_spy = {m.measure_id: m for m in spy.measures}
    by_tlt = {m.measure_id: m for m in tlt.measures}
    assert by_spy["momentum_6_1"].reason == "unavailable"
    assert "older than 5 days" in by_spy["momentum_6_1"].detail
    assert by_spy["beta_252d"].reason == by_spy["relative_momentum_6_1"].reason == "not_meaningful"
    assert by_tlt["beta_252d"].reason == by_tlt["relative_momentum_6_1"].reason == "unavailable"


def test_a_changed_released_definition_set_is_refused(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    file = load_factor_definitions()
    entry = file.definition_sets[0].model_copy(update={"stale_after_days": 9})
    changed = file.model_copy(update={"definition_sets": [entry]})
    with sessions() as session, pytest.raises(FactorDefinitionsVersionError, match=r"0\.1\.0"):
        sync_factor_definitions(session, changed)


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    recorded: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("factors", "/factors", {"known_at": iso(VALUED_AT)}),
        ("factors-nvda", "/instruments/NVDA/factors", {"known_at": iso(VALUED_AT)}),
        ("factors-tlt", "/instruments/TLT/factors", {"known_at": iso(VALUED_AT)}),
        ("factors-aapl", "/instruments/AAPL/factors", {"known_at": iso(VALUED_AT)}),
        ("factors-nvda-earlier", "/instruments/NVDA/factors", {"known_at": "2024-06-20T00:00:00Z"}),
    )
    for name, path, params in recorded:
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded SEC facts and Alpaca closes, splits and dividends replayed "
            "into the integration test database (tests/integration/test_factors.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
