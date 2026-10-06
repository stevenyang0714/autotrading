"""M0.7 acceptance on recorded real Alpaca data (tests/fixtures/alpaca, manifest.json):
snapshots become append-only quote observations; daily bars are stored raw and split-adjusted;
a split re-bases the split-adjusted history as new versions; a past date shows that day's
basis; every price carries its feed status, and without a provider key no number is shown.
Uses its own migrated database."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.alpaca.refresh import universe
from autotrading.adapters.alpaca.snapshots import parse_time
from autotrading.adapters.sec.tickers import SecTickersJob
from autotrading.config_sync import load_sources, sync_sources
from autotrading.db.models import (
    IngestionRun,
    MarketQuote,
    PriceBar,
    RawPayload,
    Source,
    SplitEvent,
)
from autotrading.domain.market_calendar import NEW_YORK
from autotrading.domain.prices import quote_feed_status
from autotrading.domain.provenance import Provenance, end_of_day
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import market_calendar
from autotrading.main import create_app
from autotrading.repositories.facts import as_of_query
from autotrading.repositories.prices import BarIn, PriceRepository, instruments_by_symbol
from autotrading.settings import get_settings
from tests import alpaca_replay, sec_replay
from tests.alpaca_replay import DUMMY_KEY_ID, DUMMY_SECRET, FIXTURES, MANIFEST
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 6, tzinfo=UTC), end=datetime(2026, 10, 7, tzinfo=UTC))
SPLIT_DAY = date(2025, 12, 5)  # XLK 2-for-1 (recorded corporate actions)
# What a daily run on the evening before the split stored: split-adjusted equalled raw then.
BEFORE_SPLIT_FETCH = datetime(2025, 12, 4, 22, 0, tzinfo=NEW_YORK)


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


def recorded_bars(file: str, symbol: str) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = json.loads((FIXTURES / file).read_text(encoding="utf-8"))["bars"][
        symbol
    ]
    return bars


def recorded_keys() -> set[tuple[str, str, str]]:
    """(symbol, adjustment, bar time) of every recorded bar: the distinct stored keys."""
    keys = set()
    for url, name in MANIFEST["files"].items():
        if "/v2/stocks/bars" not in url:
            continue
        adjustment = "raw" if "adjustment=raw" in url else "split"
        content = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        for symbol, rows in content["bars"].items():
            keys |= {(symbol, adjustment, row["t"]) for row in rows}
    return keys


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    config = get_settings().resolved_config_dir()
    with Session(engine) as session:
        sync_sources(session, load_sources(config / "sources.yaml"))
        for source_id in ("alpaca_iex", "sec_edgar"):
            source = session.get_one(Source, source_id)
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def runner(engine: Engine) -> Iterator[IngestionRunner]:
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    registry = alpaca_replay.register_recorded(sec_replay.recorded_registry(), fixture=False)
    yield IngestionRunner(
        sessionmaker(engine),
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        registry,
    )
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


def store_pre_split_basis(engine: Engine) -> int:
    """XLK's split-adjusted closes as a run on 2025-12-04 stored them (equal to raw, as no
    split had happened yet); the replayed history then re-bases them."""
    with Session(engine) as session:
        xlk = instruments_by_symbol(session, ["XLK"])["XLK"]
        source = session.get_one(Source, "alpaca_iex")
        bars = []
        for row in recorded_bars("bars_year_01.json", "XLK"):  # raw
            bar_time = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
            if bar_time.astimezone(NEW_YORK).date() >= SPLIT_DAY:
                continue
            bars.append(
                BarIn(
                    instrument_id=xlk,
                    symbol="XLK",
                    adjustment="split",
                    bar_time=bar_time,
                    open=Decimal(str(row["o"])),
                    high=Decimal(str(row["h"])),
                    low=Decimal(str(row["l"])),
                    close=Decimal(str(row["c"])),
                    volume=int(row["v"]),
                    vwap=None,
                    trade_count=None,
                    feed="sip",
                    feed_status="end_of_day",
                    provenance=Provenance(
                        source_id=source.id,
                        source_tier=source.tier,
                        source_url="https://data.alpaca.markets/v2/stocks/bars?symbols=XLK",
                        published_at=BEFORE_SPLIT_FETCH,
                        published_at_precision="exact",
                        ingested_at=BEFORE_SPLIT_FETCH,
                        effective_from=bar_time,
                        effective_to=bar_time + timedelta(days=1),
                        as_of=bar_time,
                        license_status="licensed_personal",
                        confidence=1.0,
                    ),
                )
            )
        result = PriceRepository(session).insert_bars(bars, actor="test")
        session.commit()
    return result.inserted


@pytest.fixture(scope="module")
def runs(runner: IngestionRunner, engine: Engine) -> dict[str, Any]:
    symbols, etfs = universe(get_settings().resolved_config_dir())
    equities = [s for s in symbols if s not in etfs]
    tickers = runner.create_run(
        SecTickersJob.name, {"tickers": equities, "predecessors": {}}, WINDOW
    )
    runner.execute(tickers)
    # ETF instruments come from the first Alpaca run; store XLK's old basis after it.
    snapshots, *bar_runs = MANIFEST["runs"]
    first = runner.create_run(snapshots["job"], snapshots["params"], WINDOW)
    runner.execute(first)
    pre_split = store_pre_split_basis(engine)
    run_ids = [runner.create_run(run["job"], run["params"], WINDOW) for run in bar_runs]
    for run_id in run_ids:
        runner.execute(run_id)
    with runner.sessions() as session:
        stored = [session.get_one(IngestionRun, run_id) for run_id in [first, *run_ids]]
    return {"runs": stored, "pre_split": pre_split}


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    """Whether Alpaca keys count as configured (the host .env may or may not have them)."""

    def set_configured(value: bool) -> None:
        monkeypatch.setattr("autotrading.adapters.alpaca.provider.configured", lambda *_: value)

    return set_configured


@pytest.fixture(scope="module")
def client(engine: Engine, runs: dict[str, Any]) -> Iterator[TestClient]:
    with TestClient(
        create_app(health_checker=OkChecker(), sessions=sessionmaker(engine))
    ) as client:
        yield client


def spy_snapshot() -> dict[str, Any]:
    name = next(n for u, n in MANIFEST["files"].items() if "/snapshots" in u)
    snapshot: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["SPY"]
    return snapshot


# ---------- ingestion ----------


def test_runs_store_every_quote_and_bar(runs: dict[str, Any], engine: Engine) -> None:
    # snapshots, one year of bars, the NVDA split window, splits (M1.1)
    assert [(r.status, r.rows_conflicted) for r in runs["runs"]] == [("succeeded", 0)] * 4
    with Session(engine) as session:
        quotes = session.scalar(select(func.count()).select_from(MarketQuote))
        keys = session.execute(
            select(PriceBar.symbol, PriceBar.adjustment, PriceBar.bar_time).distinct()
        ).all()
        rows = session.scalar(select(func.count()).select_from(PriceBar))
    assert quotes == 18  # every universe symbol, one snapshot
    stored = {(symbol, adjustment, bar_time) for symbol, adjustment, bar_time in keys}
    assert stored == {(s, a, parse_time(t)) for s, a, t in recorded_keys()}
    # One row per key, plus the second versions of XLK's re-based days.
    assert rows == len(stored) + runs["pre_split"]


def test_splits_since_2016_and_the_reviewed_earlier_ones_are_stored(
    runs: dict[str, Any], engine: Engine, runner: IngestionRunner
) -> None:
    with Session(engine) as session:
        splits = {
            (s.symbol, s.ex_date): s
            for s in session.scalars(select(SplitEvent).order_by(SplitEvent.ex_date))
        }
    assert {
        (symbol, day.isoformat(), s.new_rate / s.old_rate) for (symbol, day), s in splits.items()
    } == {
        ("AAPL", "2014-06-09", 7),  # config/splits.yaml
        ("GOOGL", "2014-04-03", 2),  # config/splits.yaml
        ("AAPL", "2020-08-31", 4),
        ("NVDA", "2021-07-20", 4),
        ("GOOGL", "2022-07-18", 20),
        ("NVDA", "2024-06-10", 10),
        ("ORLY", "2025-06-10", 15),
    }
    aapl_2020 = splits[("AAPL", date(2020, 8, 31))]
    # Effective from the start of the ex-date in New York (EDT): 04:00 UTC.
    assert aapl_2020.published_at == datetime(2020, 8, 31, 4, 0, tzinfo=UTC)
    assert (aapl_2020.source_id, aapl_2020.kind) == ("alpaca_iex", "forward_split")
    aapl_2014 = splits[("AAPL", date(2014, 6, 9))]
    assert aapl_2014.source_id == "sec_edgar"
    assert "0001193125-14-228798" in aapl_2014.source_url
    # A second run adds nothing.
    params = next(r["params"] for r in MANIFEST["runs"] if r["job"] == "alpaca.splits")
    again = runner.create_run("alpaca.splits", params, Window(start=WINDOW.end, end=None))
    runner.execute(again)
    with runner.sessions() as session:
        rerun = session.get_one(IngestionRun, again)
    assert (rerun.status, rerun.rows_inserted, rerun.rows_unchanged) == ("succeeded", 0, 7)


@pytest.mark.parametrize(
    "statement", ["UPDATE split_events SET new_rate = 5", "DELETE FROM split_events"]
)
def test_split_events_are_append_only(runs: dict[str, Any], engine: Engine, statement: str) -> None:
    with Session(engine) as session, pytest.raises(DBAPIError):
        session.execute(text(statement))


def test_raw_and_split_adjusted_bars_across_the_nvda_split(
    runs: dict[str, Any], engine: Engine
) -> None:
    with Session(engine) as session:
        rows = session.scalars(
            select(PriceBar).where(
                PriceBar.symbol == "NVDA",
                PriceBar.bar_date == date(2024, 6, 7),
                PriceBar.superseded_at.is_(None),
            )
        ).all()
    by_adjustment = {row.adjustment: row for row in rows}
    raw, split = by_adjustment["raw"], by_adjustment["split"]
    assert (raw.close, split.close) == (Decimal("1208.88"), Decimal("120.89"))
    # Raw closes are public at the end of their New York day; the adjusted basis when fetched.
    assert (raw.published_at, raw.published_at_precision) == (end_of_day(date(2024, 6, 7)), "day")
    assert split.published_at_precision == "exact"
    assert split.published_at > datetime(2026, 1, 1, tzinfo=UTC)
    assert (raw.feed, raw.feed_status, raw.source_id) == ("sip", "end_of_day", "alpaca_iex")


def test_a_split_re_bases_the_adjusted_history_as_new_versions(
    runs: dict[str, Any], engine: Engine
) -> None:
    day = date(2025, 12, 4)
    with Session(engine) as session:
        versions = session.scalars(
            select(PriceBar)
            .where(
                PriceBar.symbol == "XLK", PriceBar.adjustment == "split", PriceBar.bar_date == day
            )
            .order_by(PriceBar.version)
        ).all()

        def close_known_at(known_at: datetime) -> Decimal:
            (row,) = session.scalars(
                as_of_query(PriceBar, known_at=known_at).where(
                    PriceBar.symbol == "XLK",
                    PriceBar.adjustment == "split",
                    PriceBar.bar_date == day,
                )
            ).all()
            return row.close

        before, now = close_known_at(BEFORE_SPLIT_FETCH), close_known_at(datetime.now(UTC))
        revised = session.scalar(
            select(func.count())
            .select_from(PriceBar)
            .where(PriceBar.symbol == "XLK", PriceBar.revision_reason == "revision")
        )
    assert runs["pre_split"] > 0
    assert [(v.version, v.close) for v in versions] == [
        (1, Decimal("291.07")),
        (2, Decimal("145.54")),
    ]
    assert (versions[1].revision_reason, versions[1].supersedes_id) == ("revision", versions[0].id)
    assert (before, now) == (Decimal("291.07"), Decimal("145.54"))
    assert revised == runs["pre_split"]  # every pre-split day got a new version


def test_a_rerun_adds_nothing(runner: IngestionRunner, runs: dict[str, Any]) -> None:
    window = Window(start=datetime(2026, 10, 7, tzinfo=UTC), end=datetime(2026, 10, 8, tzinfo=UTC))
    rerun_ids = alpaca_replay.replay(runner, window)
    with runner.sessions() as session:
        reruns = [session.get_one(IngestionRun, run_id) for run_id in rerun_ids]
    assert [(r.status, r.rows_inserted, r.rows_conflicted) for r in reruns] == [
        ("succeeded", 0, 0)
    ] * len(MANIFEST["runs"])


def test_keys_are_never_stored(runs: dict[str, Any], engine: Engine) -> None:
    with Session(engine) as session:
        urls = list(
            session.scalars(
                select(RawPayload.source_url).where(RawPayload.source_id == "alpaca_iex")
            )
        )
    assert urls and all(url.startswith("https://data.alpaca.markets/") for url in urls)
    assert not any(DUMMY_KEY_ID in url or DUMMY_SECRET in url for url in urls)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE market_quotes SET last = 0",
        "DELETE FROM market_quotes",
        "TRUNCATE market_quotes",
        "UPDATE price_bars SET close = 0 WHERE symbol = 'SPY'",
        "DELETE FROM price_bars WHERE symbol = 'SPY'",
        "TRUNCATE price_bars",
    ],
)
def test_prices_are_append_only(engine: Engine, runs: dict[str, Any], statement: str) -> None:
    with engine.connect() as conn, pytest.raises(DBAPIError, match=r"append-only|TRUNCATE"):
        conn.execute(text(statement))


# ---------- API ----------


def test_latest_prices_carry_their_feed_status(
    client: TestClient, provider: Callable[[bool], None]
) -> None:
    provider(True)
    body = client.get("/prices/latest", params={"symbols": "SPY,NOPE"}).json()
    spy, nope = body["quotes"]
    snapshot = spy_snapshot()
    published = datetime.fromisoformat(spy["published_at"])
    expected = quote_feed_status(
        stored_status="live_single_venue",
        published_at=published,
        now=datetime.fromisoformat(body["as_of"]),
        calendar=market_calendar(),
        provider_configured=True,
    )
    # A recorded close: end_of_day until the next session opens, stale after that.
    assert spy["feed_status"] == expected and expected in {"end_of_day", "stale"}
    assert (spy["last"], spy["prev_close"], spy["bid"], spy["ask"], spy["day_volume"]) == (
        str(snapshot["latestTrade"]["p"]),
        str(snapshot["prevDailyBar"]["c"]),
        str(snapshot["latestQuote"]["bp"]),
        str(snapshot["latestQuote"]["ap"]),
        snapshot["dailyBar"]["v"],
    )
    assert spy["venue"] == "IEX"
    assert nope == {**{k: None for k in nope}, "symbol": "NOPE", "feed_status": "unavailable"}


def test_without_a_provider_key_no_price_is_shown(
    client: TestClient, provider: Callable[[bool], None]
) -> None:
    provider(False)
    latest = client.get("/prices/latest").json()
    assert latest["provider_configured"] is False
    assert {q["feed_status"] for q in latest["quotes"]} == {"unavailable"}
    numbers = ("last", "prev_close", "change_pct", "bid", "ask", "day_volume")
    assert all(q[n] is None for q in latest["quotes"] for n in numbers)

    aapl = client.get("/instruments/AAPL/prices").json()
    assert aapl["quote"]["feed_status"] == "unavailable" and aapl["quote"]["last"] is None
    assert (aapl["closes_feed_status"], aapl["last_close"], aapl["history"]) == (
        "unavailable",
        None,
        [],
    )
    assert aapl["high_52w"] is None and aapl["pct_below_52w_high"] is None

    markets = client.get("/overview").json()["blocks"][0]
    assert markets["id"] == "markets"
    assert {(t["feed_status"], t["last"]) for t in markets["prices"]} == {("unavailable", None)}
    assert (markets["indicators"], markets["charts"], markets["insight"]) == ([], [], None)


def test_a_past_date_shows_that_days_split_basis(
    client: TestClient, provider: Callable[[bool], None]
) -> None:
    provider(True)
    before = client.get(
        "/instruments/NVDA/prices", params={"known_at": "2024-06-07T12:00:00-04:00"}
    ).json()
    after = client.get(
        "/instruments/NVDA/prices", params={"known_at": "2024-06-12T06:00:00-04:00"}
    ).json()
    # Midday on 06-07 that day's close is not public yet: the last close is 06-06.
    assert before["quote"] is None and before["closes_feed_status"] == "end_of_day"
    assert before["last_close"] == {"day": "2024-06-06", "close": "1209.98"}
    assert {p["day"]: p["close"] for p in before["history"]}["2024-06-03"] == "1150.0000"
    after_history = {p["day"]: p["close"] for p in after["history"]}
    assert after["last_close"] == {"day": "2024-06-11", "close": "120.91"}
    assert after_history["2024-06-03"] == "115.0000"  # re-based: no cliff at the split
    assert after_history["2024-06-07"] == "120.8880"  # 1208.88 / 10


def test_the_day_change_across_a_split_uses_one_basis(
    client: TestClient, provider: Callable[[bool], None]
) -> None:
    provider(True)
    body = client.get(
        "/instruments/XLK/prices", params={"known_at": "2025-12-06T12:00:00-05:00"}
    ).json()
    assert body["last_close"] == {"day": "2025-12-05", "close": "146.6"}
    # 291.07 / 2 on the post-split basis (the provider rounds it to 145.54).
    assert body["previous_close"] == {"day": "2025-12-04", "close": "145.5350"}
    assert body["close_change_pct"] == "0.73"  # not -49.63 (raw 146.60 vs 291.07)


def test_overview_markets_block(client: TestClient, provider: Callable[[bool], None]) -> None:
    provider(True)
    past = client.get("/overview", params={"known_at": "2026-09-30T23:59:59+08:00"}).json()
    markets = past["blocks"][0]
    spy = next(t for t in markets["prices"] if t["symbol"] == "SPY")
    raw_spy = {row["t"][:10]: row["c"] for row in recorded_bars("bars_year_01.json", "SPY")}
    # "As known on 2026-09-30" is 11:59 that day in New York: the 09-29 close is the newest.
    assert (spy["feed_status"], spy["last"]) == ("end_of_day", str(raw_spy["2026-09-29"]))
    assert past["market"] is None
    assert [i["term_id"] for i in markets["indicators"]] == [
        "price_change_1d",
        "pct_below_52w_high",
    ]
    assert markets["charts"][0]["term_id"] == "price_history"
    assert "consolidated close" in markets["insight"]["text"]

    live = client.get("/overview").json()
    assert live["market"] is not None
    assert len(live["blocks"][0]["prices"]) == 8


def test_runs_list_keeps_the_newest_per_job(client: TestClient) -> None:
    runs = client.get("/ingestion-runs", params={"per_job": 1}).json()
    jobs = [run["job"] for run in runs]
    assert sorted(jobs) == sorted(set(jobs))
    assert {"alpaca.snapshots", "alpaca.daily_bars", "sec.tickers"} <= set(jobs)


def test_data_health_judges_alpaca_by_market_session(
    client: TestClient, provider: Callable[[bool], None]
) -> None:
    provider(True)
    sources = {s["id"]: s for s in client.get("/data-health").json()["sources"]}
    alpaca = sources["alpaca_iex"]
    assert alpaca["freshness"] in {"fresh", "stale"}
    assert alpaca["next_refresh_at"] is not None


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient, provider: Callable[[bool], None]) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    recorded: tuple[tuple[bool, str, str, dict[str, str]], ...] = (
        (True, "prices-latest", "/prices/latest", {}),
        (True, "instrument-prices-aapl", "/instruments/AAPL/prices", {}),
        (
            True,
            "instrument-prices-nvda-before-split",
            "/instruments/NVDA/prices",
            {"known_at": "2024-06-07T12:00:00-04:00"},
        ),
        (True, "overview-markets", "/overview", {}),
        (False, "prices-latest-no-key", "/prices/latest", {}),
        (False, "instrument-prices-aapl-no-key", "/instruments/AAPL/prices", {}),
    )
    for configured, name, path, params in recorded:
        provider(configured)
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded Alpaca fixtures replayed into the integration test "
            "database (tests/integration/test_prices.py), provider "
            + ("configured" if configured else "not configured"),
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
