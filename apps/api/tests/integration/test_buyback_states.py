"""Buyback states (M1.4b, ADR-025, errata E7) over the recorded SEC, Alpaca, FRED and news data:
storage, reproducibility (acceptance 1), announcements alone (acceptance 2) and the API."""

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
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.fred.series import FredSeriesJob
from autotrading.adapters.sec.refresh import universe_predecessors
from autotrading.adapters.sec.tickers import SecTickersJob
from autotrading.api.buyback_states import (
    evaluate,
    evaluate_universe,
    load_rules,
    stored_rule_set,
)
from autotrading.config_sync import (
    BuybackRulesVersionError,
    load_macro_series,
    load_sources,
    sync_buyback_rules,
    sync_macro_series,
    sync_sources,
)
from autotrading.db.models import (
    BuybackStateAssignment,
    FilingBuybackStatement,
    FinancialFact,
    Identifier,
    Instrument,
    Source,
)
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION
from autotrading.domain.provenance import end_of_day
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.facts import FinancialFactRepository
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay, news_replay
from tests.factories import financial_fact, provenance
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry, replay

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
VALUED_AT = datetime(2026, 10, 6, 12, tzinfo=UTC)  # the recorded closes end on 2026-10-05
MONTH_END = end_of_day(date(2026, 3, 31))
CONFIG = get_settings().resolved_config_dir()


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
        sync_buyback_rules(session, load_rules())
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
    """Replay the recorded data, then evaluate every universe equity at VALUED_AT and at a
    month end, both as the database holds it now; returns that system time."""
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    runner = IngestionRunner(
        sessions,
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        news_replay.register_recorded(
            alpaca_replay.register_recorded(
                fred_replay.register_recorded(recorded_registry()), fixture=False
            ),
            fixture=False,
        ),
    )
    replay(
        runner,
        WINDOW,
        universe_predecessors(CONFIG),
        before_instances=lambda: alpaca_replay.replay_splits(runner, WINDOW),
    )
    for job, params in (
        ("alpaca.daily_bars", alpaca_replay.recorded_params("alpaca.daily_bars")),
        (
            FredSeriesJob.name,
            {"series_id": "DGS10", "observation_start": fred_replay.RECORDED_SERIES["DGS10"]},
        ),
    ):
        runner.execute(runner.create_run(job, params, WINDOW))
    # NVIDIA as a listed universe company without recorded filings: its press releases
    # (the 2026-09-28 authorization increase) are its only buyback evidence.
    runner.execute(
        runner.create_run(SecTickersJob.name, {"tickers": ["NVDA"], "predecessors": {}}, WINDOW)
    )
    news_replay.replay(runner, WINDOW)
    with sessions() as session:
        now = session.execute(select(func.now())).scalar_one()
        for at in (MONTH_END, VALUED_AT):
            evaluate_universe(session, at, now, "manual")  # the active rule set, 0.2.0
        # The retired 0.1.0 too: its assignments must stay reproducible.
        evaluate_universe(session, MONTH_END, now, "manual", stored_rule_set(session, "0.1.0"))
    yield now
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def client(sessions: sessionmaker[Session], stored: datetime) -> Iterator[TestClient]:
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        yield client


def assignment(
    session: Session, ticker: str, at: datetime, rule_version: str = "0.2.0"
) -> BuybackStateAssignment:
    return session.scalars(
        select(BuybackStateAssignment).where(
            BuybackStateAssignment.ticker == ticker,
            BuybackStateAssignment.known_at == at,
            BuybackStateAssignment.rule_version == rule_version,
        )
    ).one()


def conditions(row: BuybackStateAssignment) -> dict[str, dict[str, Any]]:
    return {c["condition_id"]: c for c in row.assessment["conditions"]}


def test_each_assignment_stores_its_rule_version_inputs_thresholds_and_evidence(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    with sessions() as session:
        rows = session.scalars(
            select(BuybackStateAssignment).where(
                BuybackStateAssignment.known_at == VALUED_AT,
                BuybackStateAssignment.rule_version == "0.2.0",
            )
        ).all()
        assert sorted(r.ticker for r in rows) == ["AAPL", "META", "NVDA", "XOM"]
        apple = assignment(session, "AAPL", VALUED_AT)
    assert (apple.rule_version, apple.extractor_version, apple.system_time) == (
        "0.2.0",
        EXTRACTOR_VERSION,
        stored,
    )
    assert apple.backfilled  # evaluated after T
    assert apple.state == apple.assessment["state"] == "active"
    found = conditions(apple)
    assert {k: (c["status"], c["value"], c["threshold"]) for k, c in found.items()} == {
        "watch.announcement": ("pass", "159", "365"),
        "watch.remaining": ("fail", None, "2"),
        "active.quarter_repurchase": ("pass", "0.61", "0"),  # a mega cap (B13)
        "active.diluted_shares": ("pass", "-1.56", "-1"),
        "high_conviction.fcf_funding": ("pass", "0.60", "1.2"),
        "high_conviction.net_debt": ("pass", "-31.53", "10"),
        "high_conviction.fcf_yield": ("unavailable", None, "1.0"),
        "high_conviction.dcf_discount": ("fail", "-166.44", "15"),
        "trade_ready.above_average": ("pass", "3.25", "0"),
        "trade_ready.relative_return": ("pass", "1.21", "0"),
        "trade_ready.risk_check": ("unavailable", None, None),
    }
    # Evidence: the announcement with its 8-K, the 10-Q behind the quarter, the DCF version.
    announced = found["watch.announcement"]["announcements"][0]
    assert (announced["kind"], announced["day"]) == ("increase", "2026-04-30")
    assert announced["sources"][0]["accession"] == "0000320193-26-000011"
    quarter = found["active.quarter_repurchase"]["inputs"]
    assert {s["filing"]["form"] for i in quarter for s in i["sources"]} == {"10-Q"}
    assert apple.assessment["assumption_version"] is None  # the built-in default
    # FCF yield history needs 36 month ends; the test database has a year of closes.
    assert found["high_conviction.fcf_yield"]["detail"].startswith("FCF yield known at 12 month")
    assert apple.score is None
    assert apple.assessment["score"]["detail"] == "unavailable: undervaluation"
    intensity = next(
        c for c in apple.assessment["score"]["components"] if c["component"] == "intensity"
    )
    assert (intensity["full"], intensity["score"]) == ("2", "99.0")  # 1.98% of a mega cap (B14)
    # Rule 0.1.0 at the month end, stored beside 0.2.0: its own thresholds.
    with sessions() as session:
        old = conditions(assignment(session, "AAPL", MONTH_END, "0.1.0"))
    assert old["active.quarter_repurchase"]["threshold"] == "0.5"


def test_recomputing_with_the_same_times_reproduces_every_assignment(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    # Acceptance 1. After the evaluation: an 8-K statement filed before T but read later, a
    # correction of a fact used, and a restatement published after T.
    with sessions() as session:
        meta = instrument(session, "META")
        late = provenance(
            source_id="sec_edgar",
            source_url="https://www.sec.gov/Archives/edgar/data/1326801/late.htm",
            published_at=datetime(2026, 9, 1, 20, tzinfo=UTC),
            effective_from=datetime(2026, 9, 1, 20, tzinfo=UTC),
            effective_to=None,
            as_of=datetime(2026, 9, 1, 20, tzinfo=UTC),
        )
        session.add(
            FilingBuybackStatement(
                **late.model_dump(),
                entity_id=meta.entity_id,
                accession_number="0001326801-26-999999",
                document="late.htm",
                document_type="8-K",
                kind="increase",
                amount=Decimal(70 * 10**9),
                remaining_amount=None,
                stated_date=None,
                sentence="Our board authorized an additional $70 billion for share repurchases.",
                rule="test",
                extractor_version=EXTRACTOR_VERSION,
            )
        )
        repurchases = session.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.entity_id == instrument(session, "AAPL").entity_id,
                FinancialFact.metric_id == "share_repurchases",
                FinancialFact.superseded_at.is_(None),
            )
            .order_by(FinancialFact.period_end.desc(), FinancialFact.published_at.desc())
            .limit(1)
        ).one()
        facts = FinancialFactRepository(session)
        for value, published, actor in (
            (repurchases.value * 2, None, "test:correction"),
            (repurchases.value * 3, datetime(2030, 1, 2, tzinfo=UTC), "test:restatement"),
        ):
            changed = financial_fact(
                entity_id=repurchases.entity_id,
                metric_id=repurchases.metric_id,
                value=str(value),
                unit=repurchases.unit,
                fiscal_period=repurchases.fiscal_period,
                period_start=repurchases.period_start,
                period_end=repurchases.period_end,
                accession_id=repurchases.accession_id,
                provenance_overrides={
                    "source_id": "sec_edgar",
                    "published_at": published or repurchases.published_at,
                },
            )
            if published is None:
                facts.correct(repurchases.id, changed, actor=actor)
            else:
                facts.insert(changed, actor=actor)
        session.commit()

    with sessions() as session:
        rows = session.scalars(select(BuybackStateAssignment)).all()
        assert len(rows) == 12  # four companies: two times under 0.2.0, one under 0.1.0
        for row in rows:
            again = evaluate(
                session,
                session.get_one(Instrument, row.instrument_id),
                row.known_at,
                row.system_time,
                stored_rule_set(session, row.rule_version),
                row.extractor_version,
            )
            assert again.model_dump(mode="json") == row.assessment, (row.ticker, row.known_at)
        # The same T with today's database sees the late 8-K and the correction.
        now = session.execute(select(func.now())).scalar_one()
        rule_set = stored_rule_set(session, "0.2.0")
        fresh = evaluate(session, instrument(session, "META"), VALUED_AT, now, rule_set)
        assert fresh.state == "watch"
        assert assignment(session, "META", VALUED_AT).state == "none"
        apple = evaluate(session, instrument(session, "AAPL"), VALUED_AT, now, rule_set)
        assert apple.model_dump(mode="json") != assignment(session, "AAPL", VALUED_AT).assessment


def test_an_announcement_without_repurchases_never_goes_past_watch(
    sessions: sessionmaker[Session], stored: datetime
) -> None:
    # Acceptance 2: NVIDIA's 2026-09-28 release, and no repurchase data in the test database.
    with sessions() as session:
        nvidia = assignment(session, "NVDA", VALUED_AT)
        meta = assignment(session, "META", VALUED_AT)
    assert nvidia.state == "watch"
    found = conditions(nvidia)
    released = found["watch.announcement"]["announcements"][0]
    assert (released["kind"], released["amount"], released["remaining_amount"]) == (
        "increase",
        "150000000000",
        "235000000000",
    )
    assert released["sources"][0]["channel"] == "press_release"
    assert (
        found["active.quarter_repurchase"]["status"],
        found["active.quarter_repurchase"]["detail"],
    ) == (
        "unavailable",
        "not reported: share repurchases",
    )
    # Meta repurchased nothing in its latest quarter: ACTIVE fails whatever else holds.
    quarter = conditions(meta)["active.quarter_repurchase"]
    assert (quarter["status"], quarter["detail"]) == (
        "fail",
        "no repurchases in the quarter ended 2026-06-30",
    )
    assert meta.state == "none"  # its last announcement (February 2024) is too old


def test_dashboard_shows_every_company_state_as_known_on_a_date(client: TestClient) -> None:
    body = client.get("/buybacks", params={"known_at": VALUED_AT.isoformat()}).json()
    assert body["rule_set"]["rule_version"] == "0.2.0"
    assert body["rule_set"]["status"] == "active"
    assert body["rule_set"]["states"]["watch"]["announcement_days"] == 365
    assert body["rule_set"]["states"]["active"]["mega_cap_min"] == "500000000000"
    assert body["rule_set"]["score"]["label"] == "default weights, unvalidated"
    rows = {c["ticker"]: c for c in body["companies"]}
    assert {t: r["assignment"]["assessment"]["state"] for t, r in rows.items()} == {
        "AAPL": "active",
        "META": "none",
        "NVDA": "watch",
        "XOM": "active",
    }
    apple = rows["AAPL"]
    assert [p["known_at"][:10] for p in apple["history"]] == ["2026-04-01", "2026-10-06"]
    assert all(p["backfilled"] for p in apple["history"])
    assert apple["announcements"][0]["day"] == "2026-04-30"
    # As known on mid-April: the month-end assignment, and no later announcement.
    april = client.get("/buybacks", params={"known_at": "2026-04-15T00:00:00Z"}).json()
    apple = next(c for c in april["companies"] if c["ticker"] == "AAPL")
    assert apple["assignment"]["known_at"] == MONTH_END.isoformat().replace("+00:00", "Z")
    assert all(e["day"] <= "2026-04-15" for e in apple["announcements"])

    rules = client.get("/buybacks/rules").json()
    assert [(r["rule_version"], r["status"]) for r in rules] == [
        ("0.2.0", "active"),
        ("0.1.0", "retired"),
    ]
    page = client.get("/instruments/AAPL/buybacks", params={"known_at": VALUED_AT.isoformat()})
    state = page.json()["state"]
    assert (state["rule_version"], state["assessment"]["state"]) == ("0.2.0", "active")
    assert len(page.json()["state_history"]) == 2


def test_rule_sets_are_registered_once_and_never_change(engine: Engine) -> None:
    rules = load_rules()
    with Session(engine) as session:
        assert sync_buyback_rules(session, rules).unchanged == ["0.2.0", "0.1.0"]
        entry = rules.rule_sets[0]
        watch = entry.states.watch.model_copy(update={"announcement_days": 180})
        edited = entry.model_copy(
            update={"states": entry.states.model_copy(update={"watch": watch})}
        )
        with pytest.raises(BuybackRulesVersionError, match=r"0\.2\.0 changed"):
            sync_buyback_rules(session, rules.model_copy(update={"rule_sets": [edited]}))
        bumped = edited.model_copy(update={"rule_version": "0.3.0", "status": "retired"})
        result = sync_buyback_rules(
            session, rules.model_copy(update={"rule_sets": [entry, bumped]})
        )
        assert result.created == ["0.3.0"]
        session.rollback()


def test_assignments_cannot_be_changed(engine: Engine, stored: datetime) -> None:
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("UPDATE buyback_state_assignments SET state = 'high_conviction'"))
    with engine.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("DELETE FROM buyback_rule_sets"))


def instrument(session: Session, ticker: str) -> Instrument:
    return session.scalars(
        select(Instrument)
        .join(Identifier, Identifier.instrument_id == Instrument.id)
        .where(Identifier.id_value == ticker, Identifier.id_namespace == "sec")
    ).one()


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    at = {"known_at": VALUED_AT.isoformat()}
    for name, path, params in (
        ("buybacks-aapl", "/instruments/AAPL/buybacks", at),
        ("buybacks-xom", "/instruments/XOM/buybacks", at),
        ("buybacks-nvda", "/instruments/NVDA/buybacks", at),
        ("buyback-states", "/buybacks", at),
        ("buyback-rules", "/buybacks/rules", {}),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded SEC, Alpaca, FRED and news fixtures replayed into the "
            "integration test database (tests/integration/test_buyback_states.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
