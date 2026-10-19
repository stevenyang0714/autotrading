"""M0.6 acceptance on recorded real FRED / ALFRED data (tests/fixtures/fred, manifest.json):
a revised series queried as known before the revision returns the first release; the API
shows the revision; reruns add nothing; observations are append-only; the key is never stored.
Uses its own migrated database."""

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
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.config_sync import load_macro_series, load_sources, sync_macro_series, sync_sources
from autotrading.db.models import IngestionRun, MacroObservation, MacroSeries, RawPayload, Source
from autotrading.domain.provenance import end_of_day
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import JobRegistry, Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.facts import as_of_query
from autotrading.settings import get_settings
from tests.fred_replay import MANIFEST, RECORDED_SERIES, register_recorded, replay
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

CASE = MANIFEST["revision_case"]  # PAYEMS 2026-08-01: 159075 (2026-09-04) -> 159015 (2026-10-02)
OBSERVED = date.fromisoformat(CASE["observation_date"])
FIRST, REVISED = CASE["first_release"], CASE["first_revision"]
BEFORE_REVISION = "2026-09-30T23:59:59+08:00"
WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))


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
    config = get_settings().resolved_config_dir()
    with Session(engine) as session:
        sync_sources(session, load_sources(config / "sources.yaml"))
        sync_macro_series(session, load_macro_series(config / "macro_series.yaml"))
        source = session.get_one(Source, "fred")
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
def runs(runner: IngestionRunner) -> list[IngestionRun]:
    run_ids = replay(runner, WINDOW)
    with runner.sessions() as session:
        return [session.get_one(IngestionRun, run_id) for run_id in run_ids]


@pytest.fixture(scope="module")
def client(engine: Engine, runs: list[IngestionRun]) -> Iterator[TestClient]:
    with TestClient(
        create_app(health_checker=OkChecker(), sessions=sessionmaker(engine))
    ) as client:
        yield client


def value_known_at(session: Session, known_at: datetime) -> Decimal:
    (row,) = session.scalars(
        as_of_query(MacroObservation, known_at=known_at).where(
            MacroObservation.series_id == "PAYEMS", MacroObservation.observation_date == OBSERVED
        )
    ).all()
    return row.value


# ---------- ingestion ----------


def test_runs_store_every_vintage_and_the_series_metadata(
    runs: list[IngestionRun], engine: Engine
) -> None:
    assert [(r.status, r.rows_conflicted) for r in runs] == [("succeeded", 0)] * len(
        RECORDED_SERIES
    )
    with Session(engine) as session:
        payems = session.get_one(MacroSeries, "PAYEMS")
        assert (payems.title, payems.frequency_short, payems.units) == (
            "All Employees, Total Nonfarm",
            "M",
            "Thousands of Persons",
        )
        assert payems.last_updated is not None


def test_as_known_before_the_revision_returns_the_first_release(
    runs: list[IngestionRun], engine: Engine
) -> None:
    with Session(engine) as session:
        before = value_known_at(session, datetime.fromisoformat(BEFORE_REVISION))
        today = value_known_at(session, datetime.now(UTC))
        versions = session.scalars(
            select(MacroObservation)
            .where(
                MacroObservation.series_id == "PAYEMS",
                MacroObservation.observation_date == OBSERVED,
            )
            .order_by(MacroObservation.version)
        ).all()
    assert before == Decimal(FIRST["value"])
    assert today == Decimal(CASE["latest"]["value"])
    first, revised = versions[0], versions[1]
    assert (first.vintage, first.published_at, first.published_at_precision) == (
        date.fromisoformat(FIRST["vintage"]),
        end_of_day(date.fromisoformat(FIRST["vintage"])),
        "day",
    )
    assert (revised.value, revised.revision_reason, revised.supersedes_id) == (
        Decimal(REVISED["value"]),
        "revision",
        first.id,
    )
    assert first.source_url == "https://fred.stlouisfed.org/series/PAYEMS"
    assert first.effective_to == datetime(2026, 8, 31, tzinfo=UTC)


def test_a_rerun_adds_nothing(runner: IngestionRunner, runs: list[IngestionRun]) -> None:
    window = Window(start=WINDOW.end, end=datetime(2026, 10, 3, tzinfo=UTC))
    rerun_ids = replay(runner, window)
    with runner.sessions() as session:
        reruns = [session.get_one(IngestionRun, run_id) for run_id in rerun_ids]
    assert [(r.status, r.rows_inserted, r.rows_conflicted) for r in reruns] == [
        ("succeeded", 0, 0)
    ] * len(RECORDED_SERIES)


def test_the_api_key_is_never_stored(engine: Engine, runs: list[IngestionRun]) -> None:
    with Session(engine) as session:
        urls = session.scalars(select(RawPayload.source_url).where(RawPayload.source_id == "fred"))
        stored = list(urls)
    assert stored and not any("api_key" in url for url in stored)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE macro_observations SET value = 0 WHERE series_id = 'PAYEMS'",
        "DELETE FROM macro_observations WHERE series_id = 'PAYEMS'",
        "TRUNCATE macro_observations",
    ],
)
def test_observations_are_append_only(
    engine: Engine, runs: list[IngestionRun], statement: str
) -> None:
    with engine.connect() as conn, pytest.raises(DBAPIError, match=r"append-only|TRUNCATE"):
        conn.execute(text(statement))


# ---------- API ----------


def test_series_list_shows_the_registry_with_latest_values(client: TestClient) -> None:
    body = client.get("/macro/series").json()
    by_id = {s["series"]["id"]: s for s in body["series"]}
    assert list(by_id)[:2] == ["CPIAUCSL", "PCEPILFE"]  # registry order
    assert len(by_id) == 17  # 11 since M0.6, 6 regime inputs since M2.1
    assert by_id["PAYEMS"]["latest"]["observation_date"] == "2026-09-01"
    assert all(s["latest"] is not None for s in by_id.values())  # all 17 are recorded
    assert body["last_refresh_at"] is not None


def test_observations_show_the_revision_and_the_first_release(client: TestClient) -> None:
    def august(params: dict[str, str]) -> dict[str, Any]:
        response = client.get("/macro/series/payems/observations", params=params)
        assert response.status_code == 200
        rows = response.json()["observations"]
        found: dict[str, Any] = next(o for o in rows if o["observation_date"] == str(OBSERVED))
        return found

    before = august({"known_at": BEFORE_REVISION})
    now = august({})
    assert (before["value"], before["revised"], before["first_release"]) == (
        FIRST["value"],
        False,
        None,
    )
    assert (now["value"], now["revised"]) == (CASE["latest"]["value"], True)
    assert now["first_release"] == {"value": FIRST["value"], "vintage": FIRST["vintage"]}
    assert now["period_end"] == "2026-08-31"


def test_unknown_series_is_404(client: TestClient) -> None:
    assert client.get("/macro/series/NOPE/observations").status_code == 404


def test_observations_since_a_date_for_charts(client: TestClient) -> None:
    # M0.9 chart: a long range in one request (up to 1,000 points), from a start date.
    body = client.get(
        "/macro/series/PAYEMS/observations", params={"since": "2025-01-01", "limit": 1000}
    ).json()
    dates = [o["observation_date"] for o in body["observations"]]
    assert dates and min(dates) >= "2025-01-01"
    assert len(dates) == len(set(dates))
    revised = [o for o in body["observations"] if o["revised"]]
    assert revised and all(o["first_release"] for o in revised)
    params = {"limit": 1001}
    assert client.get("/macro/series/PAYEMS/observations", params=params).status_code == 422


# ---------- overview (ADR-016) ----------


def blocks(client: TestClient, known_at: str | None = None) -> dict[str, dict[str, Any]]:
    params = {"known_at": known_at} if known_at else {}
    response = client.get("/overview", params=params)
    assert response.status_code == 200, response.text
    return {block["id"]: block for block in response.json()["blocks"]}


def test_overview_has_six_blocks_with_charts_and_cited_insights(client: TestClient) -> None:
    now = blocks(client)
    assert list(now) == ["markets", "inflation", "labor", "growth", "policy", "curve", "risk"]
    # No prices in this database: every market tile is unavailable, without a number (M0.7).
    markets = now.pop("markets")
    assert {(t["feed_status"], t["last"]) for t in markets["prices"]} == {("unavailable", None)}
    assert markets["insight"] is None
    for block in now.values():
        assert block["charts"] and block["charts"][0]["points"], block["id"]
        assert block["insight"]["inputs"], block["id"]
    labor = {i["term_id"]: i for i in now["labor"]["indicators"]}
    assert labor["payrolls_monthly_change"]["value"] == "29"
    assert labor["payrolls_prior_month_revision"]["value"] == "-60"
    assert "Aug 2026 revised -60K from its first release" in now["labor"]["insight"]["text"]
    revision_inputs = {
        (i["observation_date"], i["vintage"]) for i in now["labor"]["insight"]["inputs"]
    }
    assert ("2026-08-01", FIRST["vintage"]) in revision_inputs  # the first release is cited
    curve = now["curve"]["insight"]["text"]
    assert "throughout the data stored" in curve  # recorded daily data starts in 2025


def test_overview_as_known_before_the_revision(client: TestClient) -> None:
    before = blocks(client, BEFORE_REVISION)
    labor = {i["term_id"]: i for i in before["labor"]["indicators"]}
    assert labor["payrolls_monthly_change"]["as_of"] == "2026-08-01"
    assert "in Aug 2026" in before["labor"]["insight"]["text"]
    for block in before.values():
        for ref in block["insight"]["inputs"] if block["insight"] else []:
            assert ref["vintage"] <= "2026-09-30", (block["id"], ref)


def test_data_health_shows_the_next_scheduled_refresh(client: TestClient) -> None:
    sources = {s["id"]: s for s in client.get("/data-health").json()["sources"]}
    assert sources["fred"]["next_refresh_at"] is not None
    assert sources["sec_edgar"]["next_refresh_at"] is not None
    assert sources["massive"]["next_refresh_at"] is None  # not enabled


def test_progress_reads_the_project_documents(client: TestClient) -> None:
    body = client.get("/progress").json()
    milestones = {m["id"]: m for m in body["milestones"]}
    assert milestones["M0.1"]["status"] == "done"
    assert milestones["M0.6"]["done"] == milestones["M0.6"]["total"] > 0
    assert [p["number"] for p in body["phases"]] == [1, 2, 3, 4, 5, 6]
    assert body["open_decisions"][0]["id"] == "OD-3"  # OD-1 and OD-2 decided (ADR-035)
    assert body["current"]["Phase"][:1].isdigit()  # any phase, not pinned to the current one
    assert milestones["M1.1"]["status"] in ("proposed", "not_started", "in_progress", "done")


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    for name, path, params in (
        ("macro-series", "/macro/series", {}),
        ("macro-payems", "/macro/series/PAYEMS/observations", {}),
        (
            "macro-payems-before-revision",
            "/macro/series/PAYEMS/observations",
            {"known_at": BEFORE_REVISION},
        ),
        ("overview", "/overview", {}),
        ("overview-before-revision", "/overview", {"known_at": BEFORE_REVISION}),
        ("progress", "/progress", {}),
        ("data-health-sources", "/data-health", {}),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded FRED fixtures replayed into the integration test database "
            "(tests/integration/test_macro.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
