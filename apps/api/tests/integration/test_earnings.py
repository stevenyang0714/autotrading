"""Earnings events (M1.5, ADR-026) over the recorded SEC filings and Alpaca closes: acceptance
times, reaction windows without look-ahead, actuals from the matched report, guidance and the
absent consensus."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.sec.refresh import universe_predecessors
from autotrading.config_sync import load_sources, sync_sources
from autotrading.db.models import Source
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.settings import get_settings
from tests import alpaca_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry, replay

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
VALUED_AT = "2026-10-06T12:00:00Z"  # the recorded closes end on 2026-10-05
CONFIG = get_settings().resolved_config_dir()
APPLE_RELEASE = "0000320193-26-000011"  # accepted 2026-04-30 16:30:41 ET, after the close
APPLE_10Q = "0000320193-26-000013"  # accepted 2026-05-01 06:01 ET
XOM_RELEASE = "0000034088-25-000059"  # accepted 2025-10-31 06:31:49 ET, before the open
META_RELEASE = "0001326801-24-000010"  # first quarter 2024 revenue outlook


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


@pytest.fixture(scope="module")
def sessions(database_factory: Callable[[], URL]) -> Iterator[sessionmaker[Session]]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine: Engine = create_engine(url)
    with Session(engine) as session:
        sync_sources(session, load_sources(CONFIG / "sources.yaml"))
        for source in session.scalars(select(Source)):
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield sessionmaker(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def client(sessions: sessionmaker[Session]) -> Iterator[TestClient]:
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    runner = IngestionRunner(
        sessions,
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        alpaca_replay.register_recorded(recorded_registry(), fixture=False),
    )
    replay(
        runner,
        WINDOW,
        universe_predecessors(CONFIG),
        before_instances=lambda: alpaca_replay.replay_splits(runner, WINDOW),
    )
    runner.execute(
        runner.create_run(
            "alpaca.daily_bars", alpaca_replay.recorded_params("alpaca.daily_bars"), WINDOW
        )
    )
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        yield client
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


def earnings(client: TestClient, ticker: str, known_at: str = VALUED_AT) -> dict[str, Any]:
    response = client.get(f"/instruments/{ticker}/earnings", params={"known_at": known_at})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def event(body: dict[str, Any], accession: str) -> dict[str, Any]:
    return next(e for e in body["events"] if e["accession"] == accession)


def test_every_event_is_timed_by_its_acceptance(client: TestClient) -> None:
    # Acceptance 1: the EDGAR acceptance time, not only the date (01 §23).
    apple = event(earnings(client, "AAPL"), APPLE_RELEASE)
    assert (apple["accepted_at"], apple["accepted_at_precision"], apple["timing"]) == (
        "2026-04-30T20:30:41Z",
        "exact",
        "after_hours",
    )
    assert apple["items"] == ["2.02", "9.01"]
    xom = event(earnings(client, "XOM"), XOM_RELEASE)
    assert (xom["accepted_at"], xom["timing"]) == ("2025-10-31T10:31:49Z", "pre_market")
    assert all(e["accepted_at_precision"] == "exact" for e in earnings(client, "META")["events"])


def test_an_after_hours_release_reacts_from_the_next_close(client: TestClient) -> None:
    # Acceptance 2: on the evening of the release no close after it is known.
    evening = event(earnings(client, "AAPL", "2026-04-30T20:00:00-04:00"), APPLE_RELEASE)
    assert [(w["day"], w["detail"]) for w in evening["reaction"]["windows"]] == [
        (None, "no end-of-day close yet")
    ] * 3
    later = event(earnings(client, "AAPL"), APPLE_RELEASE)["reaction"]
    assert later["base_day"] == "2026-04-30"  # the close before the release
    windows = {w["label"]: w for w in later["windows"]}
    assert [windows[k]["day"] for k in ("day 0", "day +1", "day +5")] == [
        "2026-05-01",
        "2026-05-04",
        "2026-05-08",
    ]
    day0 = windows["day 0"]
    assert Decimal(day0["relative"]) == Decimal(day0["stock_return"]) - Decimal(
        day0["benchmark_return"]
    )
    assert later["volume_ratio"] is not None
    # A release before the open reacts the same day.
    xom = event(earnings(client, "XOM"), XOM_RELEASE)["reaction"]
    assert (xom["base_day"], xom["windows"][0]["day"]) == ("2025-10-30", "2025-10-31")


def test_actuals_wait_for_the_10q(client: TestClient) -> None:
    # E2: the release has no XBRL; the 10-Q came the next morning.
    evening = event(earnings(client, "AAPL", "2026-04-30T20:00:00-04:00"), APPLE_RELEASE)
    assert (evening["report"], evening["actuals"]) == (None, [])
    assert evening["report_detail"] == "10-Q for the period to 2026-03-28 not yet public"
    later = event(earnings(client, "AAPL"), APPLE_RELEASE)
    assert (later["report"]["accession"], later["report"]["form"]) == (APPLE_10Q, "10-Q")
    found = {a["metric"]: a for a in later["actuals"]}
    revenue = found["revenue"]
    assert [revenue[k]["period_end"] for k in ("current", "prior_quarter", "year_ago")] == [
        "2026-03-28",
        "2025-12-27",
        "2025-03-29",
    ]
    assert Decimal(revenue["change_yoy"]) == (
        (Decimal(revenue["current"]["value"]) / Decimal(revenue["year_ago"]["value"]) - 1) * 100
    ).quantize(Decimal("0.01"))
    assert found["gross_margin"]["change_unit"] == "percentage points"
    assert found["eps_diluted"]["current"]["value"] is not None  # a reported three-month EPS
    sources = {s["filing"]["accession"] for i in revenue["current"]["inputs"] for s in i["sources"]}
    assert APPLE_10Q in sources


def test_guidance_and_the_absent_consensus(client: TestClient) -> None:
    meta = event(earnings(client, "META"), META_RELEASE)
    assert meta["guidance_status"] == "extracted"
    assert [(g["metric"], g["low"], g["high"], g["period"]) for g in meta["guidance"]] == [
        ("revenue", "34500000000", "37000000000", "first quarter 2024")
    ]
    apple = earnings(client, "AAPL")
    assert event(apple, APPLE_RELEASE)["guidance_status"] == "none"  # read, nothing numeric
    unread = [e for e in apple["events"] if e["accession"] not in (APPLE_RELEASE,)]
    assert {e["guidance_status"] for e in unread} >= {"not_read"}
    # Acceptance 3: consensus is never estimated (errata E6).
    for body in (apple, earnings(client, "XOM"), earnings(client, "META")):
        assert {json.dumps(e["consensus"]) for e in body["events"]} == {
            json.dumps(
                {
                    "eps": None,
                    "revenue": None,
                    "surprise": None,
                    "detail": "Data unavailable: no consensus provider (OD-3)",
                }
            )
        }


def test_a_past_date_shows_only_events_public_then(client: TestClient) -> None:
    before = earnings(client, "AAPL", "2026-04-30T16:00:00-04:00")
    assert APPLE_RELEASE not in {e["accession"] for e in before["events"]}
    assert all(e["accepted_at"] <= "2026-04-30T20:00:00Z" for e in before["events"])


def test_dashboard_lists_each_company_latest_release(client: TestClient) -> None:
    body = client.get("/earnings", params={"known_at": VALUED_AT}).json()
    latest = {row["ticker"]: row for row in body["latest"]}
    assert sorted(latest) == ["AAPL", "META", "XOM"]
    assert all(row["consensus"]["eps"] is None for row in body["latest"])
    assert body["recent"] == sorted(body["recent"], key=lambda r: r["accepted_at"], reverse=True)
    assert APPLE_RELEASE in {r["accession"] for r in body["recent"]}


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    at = {"known_at": VALUED_AT}
    for name, path, params in (
        ("earnings-aapl", "/instruments/AAPL/earnings", at),
        (
            "earnings-aapl-evening",
            "/instruments/AAPL/earnings",
            {"known_at": "2026-04-30T20:00:00-04:00"},
        ),
        ("earnings-meta", "/instruments/META/earnings", at),
        ("earnings-dashboard", "/earnings", at),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded SEC filings and Alpaca closes replayed into the "
            "integration test database (tests/integration/test_earnings.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
