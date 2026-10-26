"""M3.7b acceptance on recorded real FinMind responses (tests/fixtures/finmind, ADR-040) after
the recorded TWSE sessions: FinMind fills the sessions TWSE has not, never touches a TWSE row
(TW24), agrees with TWSE on the shared session (TW19), stores flows and foreign holdings known
from the end of their Taipei day, turns ex-dividend results into events (TW20), stores nothing
twice, and records a changed value as a revision public at the fetch day (TW18). Uses its own
migrated database.
"""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx2 as httpx
import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.finmind.client import DIVIDENDS, PRICE, FinMindClient
from autotrading.config_sync import (
    load_factor_definitions,
    load_sources,
    sync_factor_definitions,
    sync_sources,
)
from autotrading.db.models import (
    DividendEvent,
    ExchangeMeasure,
    IngestionRun,
    PriceBar,
    Source,
    SplitEvent,
)
from autotrading.domain.provenance import end_of_day
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.repositories.exchange_measures import measures
from autotrading.repositories.factors import backfill_points, stored_definitions
from autotrading.repositories.prices import instruments_by_symbol
from autotrading.settings import get_settings
from tests import finmind_replay, twse_replay
from tests.finmind_replay import RecordedFinMindFlows, history_params, recorded_client, serve
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

TAIPEI = ZoneInfo("Asia/Taipei")
D1, D2 = date(2026, 10, 21), date(2026, 10, 22)
FIRST_FINMIND = date(2026, 10, 1)
WINDOW = Window(start=datetime(2026, 10, 26, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC))


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
        for source_id in ("twse_openapi", "finmind"):
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
    registry: JobRegistry = {}
    yield IngestionRunner(
        sessionmaker(engine),
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        finmind_replay.register_recorded(twse_replay.register_recorded(registry)),
    )
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def history(runner: IngestionRunner) -> list[IngestionRun]:
    """The TWSE sessions first (they create the instruments), then the FinMind history."""
    twse_replay.replay(runner, WINDOW, ["d1", "d2"])
    run_ids = finmind_replay.replay_history(runner, WINDOW)
    with runner.sessions() as session:
        return [session.get_one(IngestionRun, run_id) for run_id in run_ids]


def _runs(runs: list[IngestionRun], dataset: str, code: str) -> IngestionRun:
    return next(r for r in runs if r.params["dataset"] == dataset and r.params["code"] == code)


def test_finmind_fills_the_sessions_twse_has_not_and_agrees_on_the_shared_one(
    engine: Engine, history: list[IngestionRun]
) -> None:
    assert all(r.status == "succeeded" for r in history), [r.error_message for r in history]
    prices = _runs(history, PRICE, "2330")
    assert not any("differs from the stored TWSE" in n for n in prices.notes)  # TW19
    with Session(engine) as session:
        (instrument_id,) = instruments_by_symbol(session, ["2330"], "twse").values()
        bars = session.scalars(
            select(PriceBar)
            .where(PriceBar.instrument_id == instrument_id, PriceBar.superseded_at.is_(None))
            .order_by(PriceBar.bar_date)
        ).all()
        by_day = {b.bar_date: b for b in bars}
        assert min(by_day) == FIRST_FINMIND and max(by_day) == D2
        # the TWSE rows stay the TWSE rows, version 1 (TW24)
        assert (by_day[D1].source_id, by_day[D1].version, by_day[D1].feed) == (
            "twse_openapi",
            1,
            "twse",
        )
        assert (by_day[D2].source_id, by_day[D2].version) == ("twse_openapi", 1)
        finmind_bars = [b for b in bars if b.source_id == "finmind"]
        assert len(finmind_bars) == len(bars) - 2
        earlier = by_day[date(2026, 10, 20)]
        assert (earlier.feed, earlier.source_tier, earlier.close) == (
            "finmind",
            2,
            Decimal("2405.0"),
        )
        assert earlier.published_at == end_of_day(date(2026, 10, 20), "Asia/Taipei")
        assert earlier.confidence == Decimal("1.000")  # the shared session matched
        assert earlier.source_url.startswith("https://api.finmindtrade.com/api/v4/data?")
        # the margin and valuation of 2026-10-21 are still TWSE's; 2026-10-20 is FinMind's
        rows = {
            (m.session_date, m.measure_id): m
            for m in measures(
                session,
                instrument_id,
                ["margin_balance", "exchange_pe_ratio"],
                known_at=datetime(2026, 10, 27, tzinfo=UTC),
            )
        }
        assert rows[(D1, "margin_balance")].source_id == "twse_openapi"
        assert rows[(date(2026, 10, 20), "margin_balance")].source_id == "finmind"
        assert rows[(date(2026, 10, 20), "margin_balance")].value == Decimal(34401)
        assert rows[(date(2026, 10, 20), "exchange_pe_ratio")].value == Decimal("27.88")
        assert rows[(date(2026, 10, 20), "exchange_pe_ratio")].detail == "FinMind TaiwanStockPER"


def test_flows_are_known_from_the_end_of_their_taipei_day(
    engine: Engine, history: list[IngestionRun]
) -> None:
    with Session(engine) as session:
        (instrument_id,) = instruments_by_symbol(session, ["2330"], "twse").values()

        def known(at: datetime) -> list[date]:
            return [
                m.session_date
                for m in measures(session, instrument_id, ["inst_foreign_net"], known_at=at)
            ]

        assert D1 not in known(datetime(2026, 10, 21, 23, 59, 59, tzinfo=TAIPEI))
        assert D1 in known(datetime(2026, 10, 22, 23, 59, 59, tzinfo=TAIPEI))
        found = {
            m.measure_id: m
            for m in measures(
                session,
                instrument_id,
                ["inst_foreign_net", "inst_total_net", "foreign_ratio", "shares_issued"],
                known_at=datetime(2026, 10, 27, tzinfo=UTC),
                since=D1,
                until=D1,
            )
        }
        assert found["inst_foreign_net"].unit == "shares"  # migration 0032
        assert found["foreign_ratio"].value == Decimal("68.63")
        assert found["shares_issued"].value == Decimal(25932370067)
        assert "Foreign_Investor" in (found["inst_foreign_net"].detail or "")
        assert found["inst_total_net"].source_tier == 2


def test_ex_dividend_results_become_events(engine: Engine, history: list[IngestionRun]) -> None:
    fubon = _runs(history, DIVIDENDS, "2881")
    assert fubon.status == "succeeded" and fubon.rows_inserted == 16
    with Session(engine) as session:
        (instrument_id,) = instruments_by_symbol(session, ["2881"], "twse").values()
        cash = session.scalars(
            select(DividendEvent).where(DividendEvent.instrument_id == instrument_id)
        ).all()
        stock = session.scalars(
            select(SplitEvent).where(SplitEvent.instrument_id == instrument_id)
        ).all()
        assert len(cash) == 11 and len(stock) == 5
        latest = max(cash, key=lambda d: d.ex_date)
        assert (latest.ex_date, latest.rate, latest.source_id) == (
            date(2026, 7, 1),
            Decimal("4.25"),
            "finmind",
        )
        first_stock = min(stock, key=lambda s: s.ex_date)
        assert (first_stock.ex_date, first_stock.new_rate, first_stock.kind) == (
            date(2021, 9, 6),
            Decimal("1.1000"),
            "stock_dividend",
        )
        assert first_stock.published_at == datetime(2021, 9, 5, 16, 0, tzinfo=UTC)  # Taipei start


def test_the_same_history_again_stores_nothing(
    engine: Engine, runner: IngestionRunner, history: list[IngestionRun]
) -> None:
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(ExchangeMeasure))
    run_id = runner.create_run(
        "finmind.history", {**history_params("2330", PRICE), "slot": "again"}, WINDOW
    )
    runner.execute(run_id)
    with Session(engine) as session:
        again = session.get_one(IngestionRun, run_id)
        assert again.status == "succeeded" and again.rows_inserted == 0
        assert again.rows_unchanged > 0
        assert session.scalar(select(func.count()).select_from(ExchangeMeasure)) == before


class RevisedFlows(RecordedFinMindFlows):
    """The recorded flows with 2330's foreign net buying of 2026-10-21 changed by one share:
    synthetic input built in memory from the recorded file, labelled here."""

    name: ClassVar[str] = "finmind.flows"

    def client(self) -> FinMindClient:
        def revised(request: httpx.Request) -> httpx.Response:
            response = serve(request)
            if "TaiwanStockInstitutionalInvestorsBuySell" in str(request.url) and "2330" in str(
                request.url
            ):
                body: dict[str, Any] = json.loads(response.content)
                for row in body["data"]:
                    if row["date"] == "2026-10-21" and row["name"] == "Foreign_Investor":
                        row["buy"] = int(row["buy"]) + 1
                return httpx.Response(200, json=body)
            return response

        return recorded_client(revised)


def test_a_changed_value_becomes_a_revision_public_at_the_fetch_day(
    engine: Engine, history: list[IngestionRun]
) -> None:
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    registry: JobRegistry = {}
    register_job(RevisedFlows, registry)
    runner = IngestionRunner(
        sessionmaker(engine),
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        registry,
    )
    try:
        run_id = finmind_replay.replay_flows(runner, WINDOW)
    finally:
        for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=bucket)
    with Session(engine) as session:
        run = session.get_one(IngestionRun, run_id)
        assert run.status == "succeeded" and run.rows_inserted == 3  # foreign buy, net, total
        (instrument_id,) = instruments_by_symbol(session, ["2330"], "twse").values()
        versions = session.scalars(
            select(ExchangeMeasure)
            .where(
                ExchangeMeasure.instrument_id == instrument_id,
                ExchangeMeasure.measure_id == "inst_foreign_net",
                ExchangeMeasure.session_date == D1,
            )
            .order_by(ExchangeMeasure.version)
        ).all()
        assert [v.version for v in versions] == [1, 2]
        assert versions[1].value == versions[0].value + 1
        assert versions[1].revision_reason == "revision"
        assert versions[1].published_at > versions[0].published_at  # TW18: the fetch day
        # as known before the fetch day, the first value still stands
        before = measures(
            session,
            instrument_id,
            ["inst_foreign_net"],
            known_at=datetime(2026, 10, 23, tzinfo=UTC),
            since=D1,
            until=D1,
        )
        assert [m.value for m in before] == [versions[0].value]


def test_taiwan_backfill_points_are_taipei_sessions(
    engine: Engine, history: list[IngestionRun]
) -> None:
    """TW17: the Taiwan factor backfill walks 0050's sessions and Taipei month ends."""
    with Session(engine) as session:
        definitions = stored_definitions(session, "0.3.0")
        assert definitions is not None and definitions.market == "TW"
        points = backfill_points(session, definitions, 2026, datetime(2026, 10, 27, tzinfo=UTC))
        assert points, "0050 has sessions in 2026 (the recorded TWSE days)"
        for point, _scope in points:
            assert point.astimezone(TAIPEI).strftime("%H:%M:%S") == "23:59:59"
        assert (end_of_day(D1, "Asia/Taipei"), "price") in points
        assert (end_of_day(date(2026, 9, 30), "Asia/Taipei"), "all") in points
