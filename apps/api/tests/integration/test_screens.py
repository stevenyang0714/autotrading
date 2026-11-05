"""M3.11 acceptance on recorded real TWSE and FinMind responses (ADR-042): the Taiwan screens
backfilled over October 2026 to 2026-10-21 and judged for 2026-10-22 by a manual run, from the
stored data (every listed company from the TWSE files, six of them with a FinMind history), each
run recomputing identically (screen rules 0.1.0); the not-judged row for a session whose files
have not come; the report pushed once; the candidates whose flows FinMind fetches; 0.2.0 not
judging while most histories are missing. Uses its own migrated database and stays small for CI.
"""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.finmind import refresh as finmind_refresh
from autotrading.adapters.finmind.client import INSTITUTIONAL
from autotrading.config_sync import (
    ScreenRulesVersionError,
    load_delivery_rules,
    load_screen_rules,
    load_sources,
    sync_delivery_rules,
    sync_screen_rules,
    sync_sources,
)
from autotrading.db.models import ScreenDelivery, ScreenRun, Source
from autotrading.domain.markets import TW
from autotrading.domain.screens import ScreenRulesFile, ScreenRunOut
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import JobRegistry, Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import market_calendar
from autotrading.main import create_app
from autotrading.repositories import delivery, screens
from autotrading.repositories.universe import taiwan_universe
from autotrading.settings import get_settings
from tests import finmind_replay, twse_replay
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

D1, D2 = date(2026, 10, 21), date(2026, 10, 22)
WINDOW = Window(start=datetime(2026, 10, 26, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC))
SINCE = date(2026, 10, 1)
# Six of the recorded companies hold 60 sessions of history, so the active rules (0.2.0 on) do
# not judge (SC10, the last test); the runs, watch lists and report are exercised with 0.1.0
JUDGED_WITH = "0.1.0"


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    config = get_settings().resolved_config_dir()
    with Session(engine) as session:
        sync_sources(session, load_sources(config / "sources.yaml"))
        sync_screen_rules(session, load_screen_rules(config / "screen_rules.yaml"))
        sync_delivery_rules(session, load_delivery_rules(config / "delivery_rules.yaml"))
        for source_id in ("twse_openapi", "finmind"):
            source = session.get_one(Source, source_id)
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def backfilled(engine: Engine) -> list[ScreenRun]:
    """The TWSE sessions (every listed company), then the FinMind history (2330 and 2881's
    ex-dividend results, six longer price histories), then the screens from October to D1."""
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    registry: JobRegistry = {}
    runner = IngestionRunner(
        sessionmaker(engine),
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        finmind_replay.register_recorded(twse_replay.register_recorded(registry)),
    )
    try:
        twse_replay.replay(runner, WINDOW, ["d1", "d2"])
        finmind_replay.replay_history(runner, WINDOW)
        finmind_replay.replay_prices(runner, WINDOW)
    finally:
        for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=bucket)
    with Session(engine) as session:
        rules = screens.stored_screen_rules(session, JUDGED_WITH)
        assert rules is not None
        held = session.execute(select(func.now())).scalar_one()
        screens.backfill(session, rules, held, since=SINCE, until=D1)
        return list(
            session.scalars(
                select(ScreenRun).where(ScreenRun.trigger == "backfill").order_by(ScreenRun.session)
            )
        )


@pytest.fixture(scope="module")
def live(engine: Engine, backfilled: list[ScreenRun]) -> ScreenRun:
    """A manual run at T = S = now: D2 is the newest stored session not judged yet."""
    with Session(engine) as session:
        rules = screens.stored_screen_rules(session, JUDGED_WITH)
        assert rules is not None
        now = session.execute(select(func.now())).scalar_one()
        row = screens.record_live(session, rules, now, "manual", market_calendar(TW.exchange))
        session.commit()
        assert row is not None
        session.refresh(row)
        session.expunge(row)
        return row


def test_october_is_judged_from_the_stored_data_and_recomputes_identically(
    engine: Engine, backfilled: list[ScreenRun], live: ScreenRun
) -> None:
    assert backfilled[-1].session == D1 and backfilled[0].session >= SINCE
    assert all(r.status == "judged" and r.backfilled for r in backfilled)
    assert backfilled[0].previous_id is None
    assert all(b.previous_id == a.id for a, b in pairwise(backfilled))
    assert (live.session, live.status, live.trigger, live.backfilled) == (
        D2,
        "judged",
        "manual",
        False,
    )
    assert live.previous_id == backfilled[-1].id and live.known_at == live.system_time
    last = ScreenRunOut.model_validate(live.document)
    # 1,087 listed companies (receipts left out); 1,083 traded in the sessions before D2 and
    # 1,077 of them on D2 (7 had no trade); six have 60 sessions of history
    assert (last.coverage.listed, last.coverage.expected, last.coverage.covered) == (
        1087,
        1083,
        1077,
    )
    assert last.coverage.ratio is not None and last.coverage.ratio >= rules_coverage()
    assert last.coverage.read == 6 and last.coverage.unavailable == {
        "history": 1071,
        "no_trade": 10,
    }
    assert last.industry_basis == "as_known"  # the backfill's is "first_known 2026-10-21"
    assert backfilled[-1].document["industry_basis"].startswith("first_known 2026-10-2")
    swing = last.screens[0]
    fubon = next(x for x in swing.lines if x.code == "2881")
    assert fubon.state == "on_watch" and fubon.entered < D2
    assert fubon.source is not None and fubon.source.feed == "twse"  # the TWSE bar of D2
    assert live.counts["screens"]["tw_swing_trend"]["meeting"] == swing.meeting
    with Session(engine) as session:
        for row in (backfilled[0], backfilled[-1], live):
            assert screens.same(row, screens.recompute(session, row)), row.session
        # a released rule version cannot change under the same number
        changed = load_screen_rules(get_settings().resolved_config_dir() / "screen_rules.yaml")
        content: dict[str, Any] = changed.model_dump(mode="json")
        content["rule_sets"][0]["watch_sessions"] = 21
        with pytest.raises(ScreenRulesVersionError, match="not bumped"):
            sync_screen_rules(session, ScreenRulesFile.model_validate(content))
        session.rollback()


def test_a_session_whose_files_have_not_come_is_not_judged(engine: Engine, live: ScreenRun) -> None:
    """SC10, SC11: every stored session is judged and the TWSE calendar names later ones, so the
    scheduled run records the latest of them as not judged."""
    with Session(engine) as session:
        rules = screens.stored_screen_rules(session, JUDGED_WITH)
        assert rules is not None
        now = session.execute(select(func.now())).scalar_one()
        row = screens.record_live(session, rules, now, "manual", market_calendar(TW.exchange))
        session.commit()
        assert row is not None and row.status == "not_judged" and row.session > D2
        assert row.reason is not None and "not stored yet" in row.reason
        assert f"latest stored session is {D2}" in row.reason
        assert not row.backfilled and row.previous_id is None


def test_the_report_is_pushed_once_and_never_a_backfilled_run(
    engine: Engine, live: ScreenRun
) -> None:
    """SC12: the manual run's report is sent once and recorded; backfilled runs never are. The
    0.1.0 run goes out under delivery rules 0.3.0, never under the active 0.5.0 (screen rules
    0.3.0)."""
    sent: list[str] = []

    def send(text: str) -> int:
        sent.append(text)
        return 500 + len(sent)

    with Session(engine) as session:
        rules = delivery.stored_delivery_rules(session, "0.3.0")
        active = delivery.stored_delivery_rules(session)
        assert rules is not None and rules.screens is not None and active is not None
        now = session.execute(select(func.now())).scalar_one()
        morning = now.astimezone(TW.zone).replace(hour=10, minute=30)  # outside quiet hours
        assert live.id not in {r.id for r in delivery.pending_screen_runs(session, active, morning)}
        pending = delivery.pending_screen_runs(session, rules, morning)
        assert live.id in {r.id for r in pending}
        assert all(not r.backfilled and r.trigger in ("schedule", "manual") for r in pending)
        assert delivery.deliver_screens(session, rules, send, morning, 10) == len(sent) >= 1
        assert any("2026-10-22 收盤" in text for text in sent)
        rows = session.scalars(select(ScreenDelivery).where(ScreenDelivery.run_id == live.id)).all()
        assert [(r.status, r.channel, r.rule_version) for r in rows] == [
            ("sent", "telegram", "0.3.0")
        ]
        before = len(sent)
        assert delivery.deliver_screens(session, rules, send, morning, 10) == 0
        assert len(sent) == before
        quiet = now.astimezone(TW.zone).replace(hour=23, minute=30)
        assert delivery.deliver_screens(session, rules, send, quiet, 10) == 0


def test_the_candidates_flows_leave_the_universe_out(engine: Engine, live: ScreenRun) -> None:
    """SC5: the latest judged run's new and watched names, then its movers, without the
    universe's codes, in runs of at most 20 codes for the institutional flows only."""
    universe = taiwan_universe()
    with Session(engine) as session:
        rules = screens.stored_screen_rules(session)
        assert rules is not None
        found = screens.candidates(session, rules, universe.codes)
    last = ScreenRunOut.model_validate(live.document)
    named = {x.code for s in last.screens for x in s.lines if x.state in ("entered", "on_watch")}
    named |= {m.code for m in last.movers}
    assert set(found) == named - set(universe.codes)
    fake = FakeRunner(sessionmaker(engine))
    codes = [f"{1101 + i}" for i in range(45)]
    finmind_refresh.start_candidate_flows(
        fake,  # type: ignore[arg-type]
        now=datetime(2026, 10, 27, 13, 30, tzinfo=UTC),
        manual=False,
        codes=codes,
    )
    assert [len(p["codes"]) for _, p in fake.created] == [20, 20, 5]
    assert {tuple(p["datasets"]) for _, p in fake.created} == {(INSTITUTIONAL,)}


def rules_coverage() -> Decimal:
    return (
        load_screen_rules(get_settings().resolved_config_dir() / "screen_rules.yaml")
        .active()
        .readiness.min_coverage
    )


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


@pytest.fixture(scope="module")
def client(engine: Engine, live: ScreenRun) -> Iterator[TestClient]:
    with TestClient(
        create_app(health_checker=OkChecker(), sessions=sessionmaker(engine))
    ) as client:
        yield client


def test_the_screens_page_reads_the_stored_runs(client: TestClient, live: ScreenRun) -> None:
    """The latest judged run with its definitions in words, its sources and a newer session not
    judged; As known on D1 the D1 run; the history counts the stocks that met each screen."""
    found = client.get("/taiwan/screens").json()
    assert found["run_id"] == str(live.id) and found["run"]["session"] == str(D2)
    assert found["demo"] is False and found["trigger"] == "manual"
    swing = found["rules"]["definitions"][0]
    assert (swing["screen_id"], swing["name_zh"]) == ("tw_swing_trend", "波段趨勢")
    assert swing["conditions"][1] == "收盤價高於 20 日均線"
    assert found["rules"]["content_sha256"] == (
        "cf10f6d4deb1059efcf5562aef9bd593732dfa2c82e8a25fa83da3df701733a9"
    )
    assert found["pending"] is not None and "not stored yet" in found["pending"]["reason"]
    assert found["industries"]["24"] == "半導體業"
    assert [s["provider"] for s in found["attribution"]["supplementary"]] == ["FinMind"]
    line = next(x for x in found["run"]["screens"][0]["lines"] if x["code"] == "2881")
    assert line["source"]["feed"] == "twse" and line["source"]["bar_id"]
    earlier = client.get("/taiwan/screens", params={"known_at": "2026-10-22T08:00:00+08:00"})
    assert earlier.json()["run"]["session"] == str(D1) and earlier.json()["pending"] is None
    history = client.get("/taiwan/screens/history").json()
    assert history["rule_version"] == "0.1.0" and history["points"][-1]["session"] == str(D2)
    assert history["points"][-1]["backfilled"] is False and history["points"][0]["backfilled"]
    assert history["industry_basis"].startswith("first_known")
    assert [s["screen_id"] for s in history["summary"]] == ["tw_swing_trend", "tw_range_breakout"]
    assert all("return" not in key for key in history["summary"][0])


def test_a_session_while_the_history_is_backfilled_is_not_judged(
    engine: Engine, live: ScreenRun
) -> None:
    """SC10 since 0.2.0: of the 1,077 companies with a bar of D2, six hold 60 sessions of
    history (the FinMind backfill of the others not run), so the active rules do not judge it."""
    with Session(engine) as session:
        rules = screens.stored_screen_rules(session)
        assert rules is not None and rules.rule_version == "0.3.0"
        now = session.execute(select(func.now())).scalar_one()
        row = screens.record_live(session, rules, now, "manual", market_calendar(TW.exchange))
        session.commit()
        assert row is not None and (row.session, row.status) == (D2, "not_judged")
        assert row.reason is not None and "6 of the 1077 companies" in row.reason
        assert "below 90%" in row.reason and row.previous_id is None


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    for name, path in (
        ("taiwan-screens", "/taiwan/screens"),
        ("taiwan-screens-history", "/taiwan/screens/history"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded TWSE and FinMind responses replayed into the integration "
            "test database (tests/integration/test_screens.py)",
            "endpoint": path,
            "params": {},
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n"
        )


class FakeRunner:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.created: list[tuple[str, dict[str, Any]]] = []

    def create_run(self, name: str, params: dict[str, Any], window: object) -> UUID:
        self.created.append((name, params))
        return UUID(int=len(self.created))
