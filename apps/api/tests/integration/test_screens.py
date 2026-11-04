"""M3.11 acceptance on recorded real TWSE and FinMind responses (ADR-042): the Taiwan screens
judged over October 2026 from the stored data (every listed company from the TWSE files, six of
them with a FinMind history), each run recomputing identically; the scheduled run's not-judged
row for a session whose files have not come; the candidates whose flows FinMind fetches. Uses
its own migrated database and stays small for CI.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.finmind import refresh as finmind_refresh
from autotrading.adapters.finmind.client import INSTITUTIONAL
from autotrading.config_sync import (
    ScreenRulesVersionError,
    load_screen_rules,
    load_sources,
    sync_screen_rules,
    sync_sources,
)
from autotrading.db.models import ScreenRun, Source
from autotrading.domain.markets import TW
from autotrading.domain.screens import ScreenRulesFile, ScreenRunOut
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import JobRegistry, Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import market_calendar
from autotrading.repositories import screens
from autotrading.repositories.universe import taiwan_universe
from autotrading.settings import get_settings
from tests import finmind_replay, twse_replay
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

D1, D2 = date(2026, 10, 21), date(2026, 10, 22)
WINDOW = Window(start=datetime(2026, 10, 26, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC))
SINCE = date(2026, 10, 1)


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    config = get_settings().resolved_config_dir()
    with Session(engine) as session:
        sync_sources(session, load_sources(config / "sources.yaml"))
        sync_screen_rules(session, load_screen_rules(config / "screen_rules.yaml"))
        for source_id in ("twse_openapi", "finmind"):
            source = session.get_one(Source, source_id)
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def backfilled(engine: Engine) -> list[ScreenRun]:
    """The TWSE sessions (every listed company), then the FinMind history (2330 and 2881's
    ex-dividend results, six longer price histories), then the screens since October."""
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
        rules = screens.stored_screen_rules(session)
        assert rules is not None
        held = session.execute(select(func.now())).scalar_one()
        screens.backfill(session, rules, held, since=SINCE)
        return list(
            session.scalars(
                select(ScreenRun).where(ScreenRun.trigger == "backfill").order_by(ScreenRun.session)
            )
        )


def test_october_is_judged_from_the_stored_data_and_recomputes_identically(
    engine: Engine, backfilled: list[ScreenRun]
) -> None:
    assert [r.session for r in backfilled][-2:] == [D1, D2]
    assert all(r.status == "judged" and r.backfilled for r in backfilled)
    assert backfilled[0].session >= SINCE and backfilled[0].previous_id is None
    assert all(b.previous_id == a.id for a, b in pairwise(backfilled))
    last = ScreenRunOut.model_validate(backfilled[-1].document)
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
    assert last.industry_basis.startswith("first_known 2026-10-21")
    swing = last.screens[0]
    fubon = next(x for x in swing.lines if x.code == "2881")
    assert fubon.state == "on_watch" and fubon.entered < D2
    assert fubon.source is not None and fubon.source.feed == "twse"  # the TWSE bar of D2
    assert backfilled[-1].counts["screens"]["tw_swing_trend"]["meeting"] == swing.meeting
    with Session(engine) as session:
        for row in (backfilled[0], backfilled[-1]):
            assert screens.same(row, screens.recompute(session, row)), row.session
        # a released rule version cannot change under the same number
        changed = load_screen_rules(get_settings().resolved_config_dir() / "screen_rules.yaml")
        content: dict[str, Any] = changed.model_dump(mode="json")
        content["rule_sets"][0]["watch_sessions"] = 21
        with pytest.raises(ScreenRulesVersionError, match="not bumped"):
            sync_screen_rules(session, ScreenRulesFile.model_validate(content))
        session.rollback()


def test_a_session_whose_files_have_not_come_is_not_judged(
    engine: Engine, backfilled: list[ScreenRun]
) -> None:
    """SC10, SC11: every stored session is judged and the TWSE calendar names later ones, so the
    scheduled run records the latest of them as not judged."""
    with Session(engine) as session:
        rules = screens.stored_screen_rules(session)
        assert rules is not None
        now = session.execute(select(func.now())).scalar_one()
        row = screens.record_live(session, rules, now, "manual", market_calendar(TW.exchange))
        session.commit()
        assert row is not None and row.status == "not_judged" and row.session > D2
        assert row.reason is not None and "not stored yet" in row.reason
        assert f"latest stored session is {D2}" in row.reason
        assert not row.backfilled and row.previous_id is None


def test_the_candidates_flows_leave_the_universe_out(
    engine: Engine, backfilled: list[ScreenRun]
) -> None:
    """SC5: the latest judged run's new and watched names, then its movers, without the
    universe's codes, in runs of at most 20 codes for the institutional flows only."""
    universe = taiwan_universe()
    with Session(engine) as session:
        rules = screens.stored_screen_rules(session)
        assert rules is not None
        found = screens.candidates(session, rules, universe.codes)
    last = ScreenRunOut.model_validate(backfilled[-1].document)
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


class FakeRunner:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.created: list[tuple[str, dict[str, Any]]] = []

    def create_run(self, name: str, params: dict[str, Any], window: object) -> UUID:
        self.created.append((name, params))
        return UUID(int=len(self.created))
