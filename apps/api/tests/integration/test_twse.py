"""M3.7 acceptance on recorded real TWSE OpenAPI files (tests/fixtures/twse, ADR-039): the
Taiwan universe's instruments, bars, exchange measures and run notes, each citing its source
and time; As known on at the Taipei day boundary; repeats unchanged; Taiwan factor snapshots
that recompute identically; nothing Taiwan in the US universe. M3.11 (ADR-042 SC1-SC3): every
listed company of the company file, with the bar, price change and trade value of those outside
the universe. Uses its own migrated database.
"""

import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.twse.client import API_BASE, COMPANIES
from autotrading.config_sync import (
    load_factor_definitions,
    load_sources,
    sync_factor_definitions,
    sync_sources,
)
from autotrading.db.models import (
    Entity,
    ExchangeMeasure,
    FactorSnapshot,
    Identifier,
    IngestionRun,
    Instrument,
    ListedCompany,
    PriceBar,
    RawPayload,
    Source,
)
from autotrading.domain.provenance import end_of_day
from autotrading.domain.twse import company_rows
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import JobRegistry, StoredPayload, Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.exchange_measures import measures
from autotrading.repositories.factors import (
    active_factor_version,
    recompute,
    record_universe,
    same,
    stored_definitions,
    targets,
)
from autotrading.repositories.listed import industry_names, listed_at, record_listed
from autotrading.repositories.prices import daily_bars, instruments_by_symbol
from autotrading.settings import get_settings
from tests.integration.conftest import alembic_config
from tests.twse_replay import FIXTURES, payload, register_recorded, replay

pytestmark = pytest.mark.integration

TAIPEI = ZoneInfo("Asia/Taipei")
D1 = date(2026, 10, 21)
WINDOW = Window(start=datetime(2026, 10, 22, tzinfo=UTC), end=datetime(2026, 10, 23, tzinfo=UTC))
CODES = ["2330", "2454", "2308", "2317", "3711", "1303", "2881", "3037", "2383", "2882", "0050"]
COMPANIES_IN_FILE = 1097  # d1's company file, depositary receipts included


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    config = get_settings().resolved_config_dir()
    with Session(engine) as session:
        sync_sources(session, load_sources(config / "sources.yaml"))
        sync_factor_definitions(
            session, load_factor_definitions(config / "factor_definitions.yaml")
        )
        source = session.get_one(Source, "twse_openapi")
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
    registry: JobRegistry = {}
    yield IngestionRunner(
        sessionmaker(engine),
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        register_recorded(registry),
    )
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def first(runner: IngestionRunner) -> IngestionRun:
    (run_id,) = replay(runner, WINDOW, ["d1"])
    with runner.sessions() as session:
        return session.get_one(IngestionRun, run_id)


D2 = date(2026, 10, 22)


@pytest.fixture(scope="module")
def second(runner: IngestionRunner, first: IngestionRun) -> IngestionRun:
    """The next session (2026-10-22), recorded on 2026-10-26: TWSE still served it then (the
    files of a session stay until the business day after the next one)."""
    (run_id,) = replay(runner, WINDOW, ["d2"])
    with runner.sessions() as session:
        return session.get_one(IngestionRun, run_id)


def test_the_first_run_creates_the_taiwan_instruments(engine: Engine, first: IngestionRun) -> None:
    assert first.status == "succeeded", first.error_message
    with Session(engine) as session:
        ids = instruments_by_symbol(session, CODES, "twse")
        assert set(ids) == set(CODES)
        rows = {
            i.id: i
            for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids.values())))
        }
        assert {(r.primary_exchange, r.currency) for r in rows.values()} == {("XTAI", "TWD")}
        assert rows[ids["0050"]].instrument_type == "etf" and rows[ids["0050"]].entity_id is None
        tsmc = session.get_one(Entity, rows[ids["2330"]].entity_id)
        assert (tsmc.name, tsmc.country) == ("台灣積體電路製造股份有限公司", "TW")
        # the US universe is untouched: no twse code is an alpaca symbol or a US target
        assert instruments_by_symbol(session, CODES) == {}
        assert not {t.symbol for t in targets(session)} & set(CODES)
        assert [t.symbol for t in targets(session, market="TW")] == CODES


def test_the_first_run_records_every_listed_company_and_its_session(
    engine: Engine, first: IngestionRun
) -> None:
    """ADR-042 SC1-SC3: every company of the company file has an instrument and a row; the 1,084
    listed outside the universe that STOCK_DAY_ALL names get their bar, price change and trade
    value (1,083 traded; 1538 did not), and nothing else."""
    with Session(engine) as session:
        listed = listed_at(session)
        assert len(listed) == COMPANIES_IN_FILE
        shipping = listed["2603"]
        assert (shipping.short_name, shipping.industry, shipping.listed_on) == (
            "長榮",
            "15",
            date(1987, 9, 21),
        )
        assert (
            listed["2330"].industry == "24"
            and listed["2330"].instrument_id
            == (instruments_by_symbol(session, ["2330"], "twse")["2330"])
        )
        row = session.get_one(ListedCompany, shipping.row_id)
        # 出表日期 2026-10-21, fetched the next day: public from the end of the Taipei day
        assert row.published_at == end_of_day(D1, "Asia/Taipei")
        assert (row.source_url, row.ingestion_run_id, row.listed) == (
            API_BASE + COMPANIES,
            first.id,
            True,
        )
        names = industry_names()
        assert names["15"] == "航運業" and {c.industry for c in listed.values()} <= set(names)
        bars = session.scalars(
            select(PriceBar).where(PriceBar.instrument_id == shipping.instrument_id)
        ).all()
        assert [(b.bar_date, b.close, b.feed) for b in bars] == [(D1, Decimal("257.50"), "twse")]
        found = {
            m.measure_id: m.value
            for m in session.scalars(
                select(ExchangeMeasure).where(
                    ExchangeMeasure.instrument_id == shipping.instrument_id
                )
            )
        }
        assert found == {"price_change": Decimal("-2.0000"), "trade_value": Decimal(2738441032)}
        outside = [c.instrument_id for code, c in listed.items() if code not in CODES]
        assert (
            session.scalar(
                select(func.count())
                .select_from(PriceBar)
                .where(PriceBar.instrument_id.in_(outside), PriceBar.bar_date == D1)
            )
            == 1083
        )
    assert "1 listed code(s) had no trade on 2026-10-21: no bar" in first.notes
    assert f"company file: {COMPANIES_IN_FILE} change(s) recorded among 1097 companies" in (
        first.notes
    )


def test_bars_and_measures_cite_their_file_and_the_taipei_day(
    engine: Engine, first: IngestionRun
) -> None:
    with Session(engine) as session:
        bars = session.scalars(select(PriceBar).where(PriceBar.symbol == "2330")).all()
        assert len(bars) == 1
        bar = bars[0]
        assert (bar.bar_date, bar.close, bar.volume, bar.trade_count) == (
            D1,
            Decimal("2420.00"),
            27095005,
            101401,
        )
        assert (bar.feed, bar.feed_status, bar.adjustment) == ("twse", "end_of_day", "raw")
        assert bar.bar_time == datetime(2026, 10, 21, 0, 0, tzinfo=TAIPEI)
        assert bar.published_at == end_of_day(D1, "Asia/Taipei")
        assert bar.published_at == datetime(2026, 10, 21, 15, 59, 59, 999999, tzinfo=UTC)
        assert bar.source_url == "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        assert (bar.source_id, bar.source_timezone, bar.ingestion_run_id) == (
            "twse_openapi",
            "Asia/Taipei",
            first.id,
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(RawPayload)
                .where(RawPayload.sha256 == bar.raw_payload_sha256)
            )
            == 1
        )

        found = {
            m.measure_id: m
            for m in session.scalars(
                select(ExchangeMeasure).where(ExchangeMeasure.symbol == "2330")
            )
        }
        assert found["exchange_pe_ratio"].value == Decimal("28.05")
        assert found["exchange_pe_ratio"].detail == "earnings and book value of 2026Q2"
        assert found["exchange_pb_ratio"].value == Decimal("9.76")
        assert found["exchange_dividend_yield"].value == Decimal("0.91")
        assert found["exchange_dividend_yield"].detail == "dividends of 2025"
        assert found["price_change"].value == Decimal("15.0000")
        assert found["margin_balance"].value == Decimal(35330)
        assert found["margin_balance"].unit == "lots"
        # the first margin file has no stored session to chain to: accepted, less sure
        assert found["margin_balance"].confidence == Decimal("0.900")
        assert found["price_change"].confidence == Decimal("1.000")
        assert {m.session_date for m in found.values()} == {D1}
        assert {m.data_mode for m in found.values()} == {"live"}
        assert "exchange_pe_ratio" in found and len(found) == 2 + 3 + 13
    assert any("first session stored: 2026-10-21" in n for n in first.notes)
    assert any("MI_MARGN dated 2026-10-21" in n for n in first.notes)


def test_a_taiwan_close_is_known_from_the_end_of_its_taipei_day(
    engine: Engine, first: IngestionRun
) -> None:
    with Session(engine) as session:
        (instrument_id,) = instruments_by_symbol(session, ["2330"], "twse").values()

        def known(at: datetime) -> list[date]:
            return [
                b.bar_date
                for b in daily_bars(
                    session,
                    instrument_id,
                    "raw",
                    since=datetime(2026, 10, 1, tzinfo=UTC),
                    until=datetime(2026, 10, 31, tzinfo=UTC),
                    known_at=at,
                )
            ]

        # As known on 2026-10-21 (23:59:59 in Singapore and Taipei) is still before the end
        # of the Taipei day: the close is known from As known on 2026-10-22.
        assert known(datetime(2026, 10, 21, 23, 59, 59, tzinfo=TAIPEI)) == []
        assert known(datetime(2026, 10, 22, 23, 59, 59, tzinfo=TAIPEI)) == [D1]
        values = measures(
            session,
            instrument_id,
            ["exchange_pe_ratio"],
            known_at=datetime(2026, 10, 22, 23, 59, 59, tzinfo=TAIPEI),
        )
        assert [m.value for m in values] == [Decimal("28.05")]


def test_the_same_files_again_change_nothing(
    engine: Engine, runner: IngestionRunner, first: IngestionRun
) -> None:
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(ExchangeMeasure))
    run_id = runner.create_run("twse.daily", {"slot": "again", "fixture_day": "d1"}, WINDOW)
    runner.execute(run_id)
    with Session(engine) as session:
        again = session.get_one(IngestionRun, run_id)
        assert again.status == "succeeded" and again.rows_inserted == 0
        assert again.rows_unchanged >= 11 + 11 * 2
        assert any("no new session: TWSE still serves 2026-10-21" in n for n in again.notes)
        # every value of the session again (margin included): unchanged, nothing added
        assert session.scalar(select(func.count()).select_from(ExchangeMeasure)) == before
        # every company of the company file and 0050; the file was not fetched again
        assert (
            session.scalar(
                select(func.count())
                .select_from(Identifier)
                .where(Identifier.id_namespace == "twse")
            )
            == COMPANIES_IN_FILE + 1
        )
        assert session.scalar(select(func.count()).select_from(ListedCompany)) == (
            COMPANIES_IN_FILE
        )


def test_taiwan_factor_snapshots_read_taipei_closes_against_0050_and_recompute(
    engine: Engine, first: IngestionRun
) -> None:
    with Session(engine) as session:
        at = session.execute(select(func.now())).scalar_one()  # T = S = now, as the daily job
        assert active_factor_version("TW") == "0.3.0"
        definitions = stored_definitions(session, "0.3.0")
        assert definitions is not None and definitions.benchmark == "0050"
        stored = record_universe(session, definitions, [(at, "all")], at, "manual")
        assert stored == len(CODES)
        rows = session.scalars(
            select(FactorSnapshot).where(FactorSnapshot.definition_version == "0.3.0")
        ).all()
        by_symbol = {r.symbol: r for r in rows}
        tsmc = by_symbol["2330"]
        assert tsmc.last_close == D1 and tsmc.feed_status == "end_of_day"
        measures_ = {m["measure_id"]: m for m in tsmc.snapshot["measures"]}
        # one close known: nothing is computed, nothing guessed
        assert measures_["momentum_12_1"]["value"] is None
        assert measures_["momentum_12_1"]["reason"] == "unavailable"
        assert "253" in measures_["momentum_12_1"]["detail"]  # sessions needed; one known
        assert measures_["beta_252d"]["reason"] == "unavailable"
        assert {m["measure_id"] for m in tsmc.snapshot["measures"]} == {
            "momentum_12_1",
            "momentum_6_1",
            "reversal_1m",
            "close_vs_sma_50",
            "close_vs_sma_200",
            "volatility_60d",
            "beta_252d",
            "relative_momentum_12_1",
            "relative_momentum_6_1",
        }
        assert by_symbol["0050"].snapshot["measures"][-1]["reason"] == "not_meaningful"
        assert all(same(r, recompute(session, r)) for r in rows)


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


@pytest.fixture(scope="module")
def client(engine: Engine, first: IngestionRun) -> Iterator[TestClient]:
    with TestClient(
        create_app(health_checker=OkChecker(), sessions=sessionmaker(engine))
    ) as client:
        yield client


AFTER_D1 = "2026-10-22T23:59:59+08:00"  # As known on 2026-10-22


def test_the_taiwan_list_cites_the_attribution_and_the_session(client: TestClient) -> None:
    found = client.get("/taiwan", params={"known_at": AFTER_D1}).json()
    assert [r["code"] for r in found["rows"]] == CODES
    tsmc = found["rows"][0]
    assert (tsmc["name_zh"], tsmc["session"], tsmc["close"], tsmc["change"]) == (
        "台積電",
        "2026-10-21",
        "2420.00",
        "15.0000",
    )
    assert found["latest_session"] == "2026-10-21" and found["missing_sessions"] == []
    assert found["benchmark"] == "0050" and found["ranked_on"] == "2026-10-21"
    assert found["market_session"]["timezone"] == "Asia/Taipei"
    text = found["attribution"]["text"]
    assert text.startswith("臺灣證券交易所 2026 上市個股日成交資訊")
    assert "政府資料開放授權條款" in text and "https://data.gov.tw/license" in text
    # As known on 2026-10-21: the session is not public yet
    earlier = client.get("/taiwan", params={"known_at": "2026-10-21T23:59:59+08:00"}).json()
    assert earlier["rows"][0]["session"] is None and earlier["latest_session"] is None


def test_a_taiwan_instrument_reads_prices_valuation_margin_and_no_flows(
    client: TestClient,
) -> None:
    found = client.get("/taiwan/instruments/2330", params={"known_at": AFTER_D1}).json()
    assert (found["name"], found["sector_zh"], found["currency"]) == ("TSMC", "半導體業", "TWD")
    price = found["price"]
    assert (price["session"], price["close"], price["reference"]) == (
        "2026-10-21",
        "2420.00",
        "2405.0000",
    )
    assert price["history_since"] == "2026-10-21" and price["sessions"] == 1
    assert price["source"]["dataset"] == "上市個股日成交資訊"
    assert price["source"]["published_at"] == "2026-10-21T15:59:59.999999Z"
    valuation = {m["measure_id"]: m for m in found["valuation"]["measures"]}
    assert valuation["exchange_pe_ratio"]["value"] == "28.05"
    assert valuation["exchange_pe_ratio"]["percentile"] is None  # one month of history
    assert valuation["exchange_pe_ratio"]["observations"] == 1
    margin = found["margin"]
    assert margin["values"]["margin_balance"] == "35330" and margin["unit"] == "lots"
    assert margin["margin_change"] == "929"  # 35330 - 34401
    assert margin["source"]["confidence"] == "0.900"
    assert found["flows"]["status"] == "unavailable" and "FinMind" in found["flows"]["reason"]
    assert found["reference_gaps"] == [] and found["missing_sessions"] == []
    assert client.get("/taiwan/instruments/9999").status_code == 404
    assert client.get("/taiwan/instruments/AAPL").status_code == 404


def test_taiwan_factors_are_read_against_0050(client: TestClient) -> None:
    found = client.get("/instruments/2330/factors").json()
    assert (found["market"], found["benchmark"], found["definition_version"]) == (
        "TW",
        "0050",
        "0.3.0",
    )
    assert found["percentile_min_observations"] == 12
    assert found["fundamentals"] is None
    assert client.get("/instruments/0050/factors").json()["instrument_type"] == "etf"
    # the Opportunity Radar's table stays the US universe
    assert all(r["ticker"] not in CODES for r in client.get("/factors").json()["rows"])
    sets = {d["definition_version"]: d["market"] for d in client.get("/factors/definitions").json()}
    assert sets == {"0.1.0": "US", "0.2.0": "TW", "0.3.0": "TW"}


def test_the_next_session_chains_its_margin_balances_to_the_stored_ones(
    engine: Engine, second: IngestionRun
) -> None:
    assert second.status == "succeeded", second.error_message
    assert not any("sessions lost" in n for n in second.notes)
    assert not any("reference price" in n for n in second.notes)  # no unexplained action
    with Session(engine) as session:
        (instrument_id,) = instruments_by_symbol(session, ["2330"], "twse").values()
        day2 = {
            m.measure_id: m
            for m in session.scalars(
                select(ExchangeMeasure).where(
                    ExchangeMeasure.instrument_id == instrument_id,
                    ExchangeMeasure.session_date == D2,
                )
            )
        }
        # the real 2026-10-22 file's previous balances equal the stored 2026-10-21 balances
        assert day2["margin_balance_previous"].value == Decimal(35330)
        assert day2["margin_balance"].confidence == Decimal("1.000")
        bars = session.scalars(
            select(PriceBar.bar_date).where(PriceBar.instrument_id == instrument_id)
        ).all()
        assert sorted(bars) == [D1, D2]
        # the company file is fetched only while an instrument is missing
        payloads = session.scalars(
            select(RawPayload.source_url).where(RawPayload.ingestion_run_id == second.id)
        ).all()
        assert not any(url.endswith("/opendata/t187ap03_L") for url in payloads)


def test_codes_held_outside_the_universe_get_their_closes_only(
    engine: Engine, runner: IngestionRunner, second: IngestionRun
) -> None:
    # ADR-041 H6: the Holdings page created 0056 (a fund) and 6488 (a TPEx code). 0056 gets its
    # close of the session and nothing else; 6488 is not on the TWSE and is noted; 2330 is the
    # universe's and 2603 a listed company's (ADR-042 SC1), stored already.
    held: dict[str, UUID] = {}
    with Session(engine) as session:
        for code in ("0056", "6488"):
            instrument = Instrument(
                instrument_type="other", primary_exchange="XTAI", currency="TWD"
            )
            session.add(instrument)
            session.flush()
            session.add(
                Identifier(
                    instrument_id=instrument.id,
                    id_type="ticker",
                    id_namespace="twse",
                    id_value=code,
                    valid_from=datetime(2026, 10, 27, tzinfo=UTC),
                    source_id="twse_openapi",
                )
            )
            held[code] = instrument.id
        session.commit()
    params = {"slot": "held", "fixture_day": "d1", "extra_codes": ["0056", "2330", "2603", "6488"]}
    run_id = runner.create_run("twse.daily", params, WINDOW)
    runner.execute(run_id)
    with Session(engine) as session:
        run = session.get_one(IngestionRun, run_id)
        assert run.status == "succeeded"
        assert "1 held code(s) not in STOCK_DAY_ALL: TPEx listings are not supported" in run.notes
        bars = session.scalars(select(PriceBar).where(PriceBar.instrument_id == held["0056"]))
        assert [(b.bar_date, b.close, b.feed) for b in bars] == [(D1, Decimal("58.75"), "twse")]
        for instrument_id in held.values():
            assert not session.scalar(
                select(func.count())
                .select_from(ExchangeMeasure)
                .where(ExchangeMeasure.instrument_id == instrument_id)
            )
        assert not session.scalar(
            select(func.count()).select_from(PriceBar).where(PriceBar.instrument_id == held["6488"])
        )


def test_a_company_the_file_stops_naming_is_no_longer_listed_from_then_on(
    engine: Engine, second: IngestionRun
) -> None:
    """ADR-042 SC2: the d1 company file again, fetched a week later and without 2603: one row
    with `listed` false; As known on before it, 2603 is still listed."""
    file = (FIXTURES / "d1_t187ap03_L.json").read_bytes()
    companies = {c.code: c for c in company_rows(payload("d1", "t187ap03_L"))}
    del companies["2603"]
    fetched = datetime(2026, 10, 29, 1, 0, tzinfo=UTC)
    stored = StoredPayload(
        object_key="test",
        sha256=hashlib.sha256(file).hexdigest(),
        content=file,
        content_type="application/json",
        source_url=API_BASE + COMPANIES,
        fetched_at=fetched,
    )
    with Session(engine) as session:
        ids = instruments_by_symbol(session, list(companies), "twse")
        source = session.get_one(Source, "twse_openapi")
        inserted, unchanged = record_listed(
            session, companies, ids, stored, source, second.id, actor="test"
        )
        session.commit()
        assert (inserted, unchanged) == (1, COMPANIES_IN_FILE - 1)
        assert "2603" not in listed_at(session)
        # the file's 出表日期 is 2026-10-21 again, so the row is public from the end of that day
        # at the latest; held before the row was recorded, 2603 is listed
        assert "2603" in listed_at(session, system_time=second.finished_at)
