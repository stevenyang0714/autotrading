"""Paper journal (M1.6, ADR-027) over the recorded SEC filings, Alpaca closes, FRED yields and
news: Thesis Cards with evidence snapshots, TRADE and NO TRADE decisions, paper performance and
replay. Writes are pinned at WRITE_AT (the recorded closes end on 2026-10-05); the system time
is always the database's."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.fred.series import FredSeriesJob
from autotrading.adapters.sec.refresh import universe_predecessors
from autotrading.api.buyback_states import (
    active_rule_version,
    load_rules,
    record_assignment,
    stored_rule_set,
)
from autotrading.api.journal import resolve, subject, write_time
from autotrading.config_sync import (
    load_macro_series,
    load_risk_rules,
    load_sources,
    sync_buyback_rules,
    sync_macro_series,
    sync_risk_rules,
    sync_sources,
)
from autotrading.db.models import (
    AuditLog,
    FinancialFact,
    PriceBar,
    RiskCheck,
    Source,
    ThesisCard,
    TradeDecision,
)
from autotrading.domain.facts import FinancialFactIn
from autotrading.domain.provenance import Provenance
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.facts import FinancialFactRepository
from autotrading.repositories.prices import BarIn, PriceRepository
from autotrading.repositories.risk import recompute
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay, news_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import recorded_registry, replay

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
WRITE_AT = datetime(2026, 9, 15, 12, tzinfo=UTC)  # Tuesday before the open: last close 09-14
VALUED_AT = datetime(2026, 10, 6, 12, tzinfo=UTC)  # the recorded closes end on 2026-10-05
CONFIG = get_settings().resolved_config_dir()
CLOCK: dict[str, datetime] = {"at": WRITE_AT}


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
        sync_risk_rules(session, load_risk_rules(CONFIG / "risk_rules.yaml"))
        for source in session.scalars(select(Source)):
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


@pytest.fixture(scope="module")
def client(sessions: sessionmaker[Session]) -> Iterator[TestClient]:
    """Replay the recorded data and evaluate AAPL's buyback state at WRITE_AT (a signal)."""
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
    news_replay.replay(runner, WINDOW)
    with sessions() as session:
        assess(session, WRITE_AT)
    app = create_app(health_checker=OkChecker(), sessions=sessions)
    app.dependency_overrides[write_time] = lambda: CLOCK["at"]
    with TestClient(app) as client:
        yield client
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


def assess(session: Session, at: datetime) -> None:
    who = subject(session, "AAPL")
    now = session.execute(select(func.now())).scalar_one()
    rules = stored_rule_set(session, active_rule_version())
    record_assignment(session, "AAPL", who.instrument, at, now, rules, "manual")
    session.commit()


def candidates(client: TestClient, ticker: str = "AAPL") -> list[dict[str, Any]]:
    response = client.get(f"/instruments/{ticker}/evidence", params={"known_at": iso(CLOCK["at"])})
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["candidates"]
    return found


def iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def ref(candidate: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    return {"kind": candidate["kind"], **candidate["ref"], "note": note}


def evidence(client: TestClient) -> list[dict[str, Any]]:
    """Five rows of different kinds: a fact, a filing, the buyback state, the close, a fact."""
    found = candidates(client)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for c in found:
        by_kind.setdefault(c["kind"], []).append(c)
    return [
        ref(by_kind["financial_fact"][0], "revenue scale"),
        ref(by_kind["filing"][0]),
        ref(by_kind["buyback_state"][0], "the rule's own reading"),
        ref(by_kind["price_close"][0]),
        ref(next(c for c in by_kind["financial_fact"] if c["snapshot"]["metric_id"] == "capex")),
    ]


def signal_ids(client: TestClient) -> list[str]:
    body = client.get("/signals", params={"known_at": iso(WRITE_AT), "ticker": "AAPL"}).json()
    return [s["id"] for s in body["history"][:1]]


def entry(client: TestClient, decision: dict[str, Any], **card: Any) -> dict[str, Any]:
    body = {
        "ticker": "AAPL",
        "thesis": "Buybacks keep shrinking the share count while free cash flow covers them.",
        "evidence": evidence(client),
        "catalysts": [{"description": "Fiscal Q4 results", "expected": "2026-10-30"}],
        "invalidation": "Repurchases fall below free cash flow for two quarters.",
        "notes": "Valuation is not cheap.",
        "signal_ids": signal_ids(client),
        "decision": decision,
        **card,
    }
    response = client.post("/journal", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


NO_TRADE = {
    "decision": "no_trade",
    "no_trade_reason": "priced_in",
    "note": "Fair value below price.",
}
TRADE = {
    "decision": "trade",
    "side": "buy",
    "quantity": "10",
    "order_type": "market",
    "max_loss": "100",
}
STATE: dict[str, Any] = {}


def test_candidates_are_rows_of_the_company_known_at_t(client: TestClient) -> None:
    found = candidates(client)
    kinds = {c["kind"] for c in found}
    assert {"financial_fact", "filing", "buyback_state", "price_close", "news"} <= kinds
    assert all(c["published_at"] <= iso(WRITE_AT) for c in found)
    close = next(c for c in found if c["kind"] == "price_close")
    assert (close["ref"], close["snapshot"]["day"]) == ({"day": "2026-09-14"}, "2026-09-14")
    state = next(c for c in found if c["kind"] == "buyback_state")
    assert state["snapshot"]["known_at"] == iso(WRITE_AT)


def test_a_no_trade_is_recorded_audited_and_listed_like_a_trade(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    # Acceptance 3: NO TRADE and TRADE share one table, one audit trail and the journal.
    skip = entry(client, NO_TRADE)
    trade = entry(client, TRADE, thesis="Buy the buyback compounder.")
    STATE.update(no_trade=skip, trade=trade)
    card = skip["card"]
    assert (card["version"], card["known_at"], len(card["evidence"])) == (1, iso(WRITE_AT), 5)
    assert card["evidence"][0]["note"] == "revenue scale"
    assert card["valuation"]["assumption_version"] is None  # the built-in default
    assert card["signal_ids"] == signal_ids(client) != []
    decision = skip["decisions"][0]
    assert (decision["decision"], decision["no_trade_reason"], decision["mode"]) == (
        "no_trade",
        "priced_in",
        "paper",
    )
    assert decision["strategy_id"] == "S1"  # from the cited signal
    assert decision["performance"]["return_pct"] == "0.00"  # nothing moved yet at T
    bought = trade["decisions"][0]
    assert bought["closes"]["stock"]["day"] == bought["closes"]["benchmark"]["day"] == "2026-09-14"
    with sessions() as session:
        rows = session.scalars(select(TradeDecision).order_by(TradeDecision.created_at)).all()
        assert [r.decision for r in rows] == ["no_trade", "trade"]
        assert {(r.mode, r.broker, r.approval_state, r.user_id) for r in rows} == {
            ("paper", None, "recorded", "steven")
        }
        audited = session.execute(
            select(AuditLog.object_type, AuditLog.actor, AuditLog.action).where(
                AuditLog.object_type.in_(["thesis_cards", "trade_decisions"])
            )
        ).all()
        assert sorted(audited) == sorted(
            [("thesis_cards", "web", "insert")] * 2 + [("trade_decisions", "web", "insert")] * 2
        )
    listed = client.get("/journal", params={"known_at": iso(WRITE_AT)}).json()["entries"]
    assert {e["decision"]["decision"] for e in listed} == {"no_trade", "trade"}
    labels = client.get("/audit-log", params={"table": "trade_decisions"}).json()
    names = {row["object_label"] for row in labels["entries"]}
    assert {"AAPL NO TRADE (priced in)", "AAPL paper TRADE buy 10"} <= names


def test_paper_performance_against_spy_and_the_exit(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    trade = STATE["trade"]
    entry_id = trade["decisions"][0]["id"]
    later = client.get(f"/journal/{trade['card']['card_id']}", params={"known_at": iso(VALUED_AT)})
    performance = later.json()["decisions"][0]["performance"]
    entry_close = Decimal(performance["entry"]["close"])
    mark = Decimal(performance["mark"]["close"])
    assert (performance["open"], performance["mark"]["day"]) == (True, "2026-10-05")
    assert Decimal(performance["return_pct"]) == ((mark / entry_close - 1) * 100).quantize(
        Decimal("0.01")
    )
    assert Decimal(performance["pnl"]) == ((mark - entry_close) * 10).quantize(Decimal("0.01"))
    assert Decimal(performance["relative"]) == Decimal(performance["return_pct"]) - Decimal(
        performance["benchmark_return_pct"]
    )
    assert performance["max_loss_breached"] == (Decimal(performance["pnl"]) < -100)
    # A NO TRADE shows the move after it, without money.
    skipped = client.get("/journal", params={"known_at": iso(VALUED_AT)}).json()["entries"]
    no_trade = next(e for e in skipped if e["decision"]["decision"] == "no_trade")
    assert no_trade["decision"]["performance"]["return_pct"] == performance["return_pct"]
    assert no_trade["decision"]["performance"]["pnl"] is None

    CLOCK["at"] = VALUED_AT
    try:
        exited = client.post(f"/journal/decisions/{entry_id}/exit", json={"note": "Target met."})
        assert exited.status_code == 201, exited.text
        again = client.post(f"/journal/decisions/{entry_id}/exit", json={})
        assert again.status_code == 409
        no_exit = STATE["no_trade"]["decisions"][0]["id"]
        assert client.post(f"/journal/decisions/{no_exit}/exit", json={}).status_code == 409
    finally:
        CLOCK["at"] = WRITE_AT
    decisions = exited.json()["decisions"]
    out = decisions[1]
    assert (out["side"], out["quantity"], out["exits_decision_id"]) == ("sell", "10", entry_id)
    assert out["closes"]["stock"]["day"] == "2026-10-05"
    assert decisions[0]["exited_by"] == out["id"]
    closed = decisions[0]["performance"]
    assert (closed["open"], closed["return_pct"]) == (False, performance["return_pct"])
    # Before the exit the trade is still open.
    before = client.get(f"/journal/{trade['card']['card_id']}", params={"known_at": iso(WRITE_AT)})
    assert [d["exited_by"] for d in before.json()["decisions"]] == [None]


def test_a_card_change_is_a_new_version(client: TestClient) -> None:
    card_id = STATE["no_trade"]["card"]["card_id"]
    body = {
        "thesis": "Still priced in after the buyback update.",
        "evidence": evidence(client)[:3],
        "invalidation": "The price falls below the base DCF.",
    }
    CLOCK["at"] = WRITE_AT + timedelta(hours=1)
    try:
        response = client.post(f"/journal/{card_id}/versions", json=body)
        assert response.status_code == 201, response.text
        CLOCK["at"] = WRITE_AT - timedelta(hours=1)
        assert client.post(f"/journal/{card_id}/versions", json=body).status_code == 409
    finally:
        CLOCK["at"] = WRITE_AT
    shown = response.json()
    assert (shown["card"]["version"], [v["version"] for v in shown["versions"]]) == (2, [1, 2])
    first = client.get(f"/journal/{card_id}", params={"version": 1}).json()["card"]
    assert first["thesis"] == STATE["no_trade"]["card"]["thesis"]
    # The decision stays with the version it was made on.
    assert shown["decisions"][0]["card_version"] == 1


def test_the_journal_is_point_in_time(client: TestClient) -> None:
    card_id = STATE["no_trade"]["card"]["card_id"]
    before = iso(WRITE_AT - timedelta(minutes=1))
    assert client.get("/journal", params={"known_at": before}).json()["entries"] == []
    assert client.get(f"/journal/{card_id}", params={"known_at": before}).status_code == 404
    at_first = client.get(f"/journal/{card_id}", params={"known_at": iso(WRITE_AT)}).json()
    assert [v["version"] for v in at_first["versions"]] == [1]


def test_a_recorded_trade_cites_its_passed_risk_check(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    # M2.3 (ADR-031): every paper TRADE entry passed a risk check at its own (T, S).
    entry_id = STATE["trade"]["decisions"][0]["id"]
    with sessions() as session:
        decision = session.get_one(TradeDecision, UUID(entry_id))
        assert decision.risk_check_id is not None and decision.portfolio_snapshot_id is not None
        check = session.get_one(RiskCheck, decision.risk_check_id)
        assert (check.verdict, check.trigger, check.ticker, check.quantity) == (
            "pass",
            "trade",
            "AAPL",
            Decimal(10),
        )
        assert (
            check.known_at == WRITE_AT
            and check.portfolio_snapshot_id == decision.portfolio_snapshot_id
        )
        again = recompute(session, check)
        assert again is not None and again.model_dump(mode="json") == check.risk_check


def test_a_vetoed_trade_is_refused_and_the_veto_recorded(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    # Acceptance 2: a vetoed paper TRADE is refused and the veto is recorded.
    with sessions() as session:
        before = session.scalar(select(func.count()).select_from(TradeDecision))
    body = {
        "ticker": "AAPL",
        "thesis": "Too big.",
        "evidence": evidence(client),
        "invalidation": "n/a",
        "decision": {**TRADE, "quantity": "1000", "max_loss": "5000"},
    }
    response = client.post("/journal", json=body)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "vetoed by risk rules 0.1.0" in detail
    assert "Position size" in detail and "Maximum loss" in detail
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TradeDecision)) == before
        veto = session.scalars(
            select(RiskCheck)
            .where(RiskCheck.verdict == "veto")
            .order_by(RiskCheck.recorded_at.desc())
        ).first()
        assert veto is not None and veto.quantity == 1000 and veto.trigger == "trade"
        audited = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.object_type == "risk_checks", AuditLog.object_id == str(veto.id))
        )
        assert audited == 1
    # A TRADE without a maximum loss is refused before any check.
    no_loss = {**body, "decision": {k: v for k, v in TRADE.items() if k != "max_loss"}}
    refused = client.post("/journal", json=no_loss)
    assert refused.status_code == 422 and "maximum loss" in refused.text


def test_the_database_refuses_a_trade_without_a_passed_check(
    client: TestClient, engine: Engine
) -> None:
    copy = (
        "INSERT INTO trade_decisions (thesis_card_id, instrument_id, ticker, signal_ids, "
        "decision, side, quantity, order_type, max_loss, entry_close, mode, approval_state, "
        "known_at, system_time, user_id, risk_check_id) SELECT thesis_card_id, instrument_id, "
        "ticker, signal_ids, 'trade', 'buy', {quantity}, 'market', 100, entry_close, mode, "
        "approval_state, known_at, system_time, user_id, {check} FROM trade_decisions "
        "WHERE decision = 'trade' AND exits_decision_id IS NULL LIMIT 1"
    )
    with engine.connect() as conn, pytest.raises(DBAPIError, match="passed risk check"):
        conn.execute(text(copy.format(quantity=10, check="NULL")))
    # A NO TRADE never carries a risk check.
    no_trade = (
        "INSERT INTO trade_decisions (thesis_card_id, instrument_id, ticker, signal_ids, "
        "decision, no_trade_reason, mode, approval_state, known_at, system_time, user_id, "
        "risk_check_id) SELECT thesis_card_id, instrument_id, ticker, signal_ids, decision, "
        "no_trade_reason, mode, approval_state, known_at, system_time, user_id, "
        "(SELECT id FROM risk_checks LIMIT 1) FROM trade_decisions WHERE decision = 'no_trade' "
        "LIMIT 1"
    )
    with engine.connect() as conn, pytest.raises(IntegrityError, match="risk_check_on_entries"):
        conn.execute(text(no_trade))
    vetoed = "(SELECT id FROM risk_checks WHERE verdict = 'veto' LIMIT 1)"
    with engine.connect() as conn, pytest.raises(DBAPIError, match="passed risk check"):
        conn.execute(text(copy.format(quantity=1000, check=vetoed)))
    passed = "(SELECT id FROM risk_checks WHERE verdict = 'pass' AND trigger = 'trade' LIMIT 1)"
    with engine.connect() as conn, pytest.raises(DBAPIError, match="another trade"):
        conn.execute(text(copy.format(quantity=11, check=passed)))
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("UPDATE risk_checks SET verdict = 'pass'"))


def test_the_paper_portfolio_and_an_on_demand_check(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    book = client.get("/portfolio", params={"known_at": iso(WRITE_AT)}).json()
    assert book["rules"]["rule_version"] == "0.1.0" and "PAPER ONLY" in book["detail"]
    position = book["portfolio"]["positions"][0]
    assert (position["ticker"], position["side"], position["sector"]) == (
        "AAPL",
        "buy",
        "information_technology",
    )
    assert Decimal(book["portfolio"]["gross"]) == Decimal(position["market_value"])
    # Before the entry the book is empty.
    empty = client.get("/portfolio", params={"known_at": iso(WRITE_AT - timedelta(days=1))}).json()
    assert empty["portfolio"]["positions"] == []
    tried = client.post(
        "/risk/checks", json={"ticker": "AAPL", "side": "buy", "quantity": "5", "max_loss": "50"}
    )
    assert tried.status_code == 201, tried.text
    found = tried.json()
    assert found["trigger"] == "on_demand"
    assert {r["limit_id"] for r in found["check"]["limits"]} == {
        "price",
        "max_loss_stated",
        "max_loss",
        "position",
        "sector",
        "volume",
        "gross",
    }
    listed = client.get("/risk/checks", params={"trigger": "on_demand"}).json()["checks"]
    assert [c["id"] for c in listed][:1] == [found["id"]]
    mixed = client.get("/risk/checks", params=[("trigger", "trade"), ("trigger", "on_demand")])
    assert {c["trigger"] for c in mixed.json()["checks"]} <= {"trade", "on_demand"}
    assert found["id"] in [c["id"] for c in mixed.json()["checks"]]
    assert (
        client.post(
            "/risk/checks", json={"ticker": "AAPL", "side": "buy", "quantity": "5", "broker": "x"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda b: b.update(evidence=b["evidence"][:2]), "at least 3"),
        (lambda b: b.update(evidence=b["evidence"] * 2), "at most 7"),
        (lambda b: b.update(evidence=[b["evidence"][0]] * 3), "listed twice"),
        (
            lambda b: b["evidence"].__setitem__(0, {"kind": "filing", "id": str(uuid4())}),
            "not a row",
        ),
        (
            lambda b: b["evidence"].__setitem__(0, {"kind": "price_close", "day": "2026-09-15"}),
            "not a row",
        ),
        (
            lambda b: b["evidence"].__setitem__(0, {"kind": "price_close", "id": str(uuid4())}),
            "takes a day",
        ),
        (
            lambda b: b.update(decision={"decision": "trade", "side": "buy"}),
            "needs a side, a quantity",
        ),
        (
            lambda b: b.update(decision={"decision": "no_trade", "no_trade_reason": "other"}),
            "needs a note",
        ),
        (lambda b: b.update(decision={**TRADE, "order_type": "limit"}), "limit price"),
        (lambda b: b.update(decision={**TRADE, "broker": "alpaca"}), "Extra inputs"),
        (lambda b: b.update(decision={**TRADE, "mode": "live"}), "Extra inputs"),
        (lambda b: b.update(signal_ids=[str(uuid4())]), "not a signal of AAPL"),
    ],
)
def test_writes_are_checked(
    client: TestClient, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    body: dict[str, Any] = {
        "ticker": "AAPL",
        "thesis": "x",
        "evidence": evidence(client),
        "invalidation": "y",
        "decision": NO_TRADE,
    }
    change(body)
    response = client.post("/journal", json=body)
    assert response.status_code == 422
    assert message in response.text


def test_another_company_row_is_not_evidence(client: TestClient) -> None:
    meta_fact = next(c for c in candidates(client, "META") if c["kind"] == "financial_fact")
    body = {
        "ticker": "AAPL",
        "thesis": "x",
        "evidence": [ref(meta_fact), *evidence(client)[:2]],
        "invalidation": "y",
        "decision": NO_TRADE,
    }
    response = client.post("/journal", json=body)
    assert (response.status_code, "not a row of AAPL" in response.text) == (422, True)


def test_no_path_can_send_an_order(client: TestClient, engine: Engine) -> None:
    # Acceptance 2: no broker, no order route, and the database refuses anything but paper.
    schema = client.get("/openapi.json").json()["paths"]
    paths = {(path, method.upper()) for path, methods in schema.items() for method in methods}
    assert not any(word in path for path, _ in paths for word in ("order", "broker", "execut"))
    assert {p for p, m in paths if m == "POST" and p.startswith("/journal")} == {
        "/journal",
        "/journal/{card_id}/versions",
        "/journal/decisions/{decision_id}/exit",
    }
    # M2.3: trying a trade against the risk limits records a check, never a decision
    assert {p for p, m in paths if m == "POST" and p.startswith("/risk")} == {"/risk/checks"}
    # M2.4-M2.5: rotation, candidates and backtests are read-only
    assert not any(
        m != "GET" and p.startswith(("/rotation", "/candidates", "/backtests", "/momentum"))
        for p, m in paths
    )
    copy = (
        "INSERT INTO trade_decisions (thesis_card_id, instrument_id, ticker, signal_ids, "
        "decision, no_trade_reason, mode, broker, approval_state, known_at, system_time, "
        "user_id) SELECT thesis_card_id, instrument_id, ticker, signal_ids, decision, "
        "no_trade_reason, {mode}, {broker}, {approval}, known_at, system_time, user_id "
        "FROM trade_decisions WHERE decision = 'no_trade' LIMIT 1"
    )
    for mode, broker, approval, check in (
        ("'live'", "NULL", "'recorded'", "paper_mode"),
        ("'paper'", "'alpaca'", "'recorded'", "no_broker"),
        ("'paper'", "NULL", "'approved'", "approval_state"),
    ):
        with engine.connect() as conn, pytest.raises(IntegrityError, match=check):
            conn.execute(text(copy.format(mode=mode, broker=broker, approval=approval)))
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("UPDATE trade_decisions SET mode = 'live'"))
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("DELETE FROM thesis_cards"))


def test_replay_is_identical_after_later_data(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    # Acceptance 1: a restatement, a correction, a revised close and a new buyback state, all
    # recorded after the card, leave its replay identical.
    card = STATE["no_trade"]["card"]
    fact_ref = card["evidence"][0]
    close_ref = next(e for e in card["evidence"] if e["kind"] == "price_close")
    with sessions() as session:
        fact = session.get_one(FinancialFact, UUID(fact_ref["ref"]["id"]))
        repository = FinancialFactRepository(session)
        # A correction public before T, and a restatement after it.
        correction = restated(fact, fact.value + 1, fact.published_at + timedelta(hours=1))
        repository.insert(correction, actor="test:ingest", reason="correction")
        restatement = restated(fact, fact.value + 2, WRITE_AT + timedelta(days=60))
        repository.insert(restatement, actor="test:ingest", reason="restatement")
        bar = session.scalars(
            select(PriceBar).where(
                PriceBar.instrument_id == fact_instrument(session),
                PriceBar.adjustment == "raw",
                PriceBar.bar_date == date.fromisoformat(close_ref["snapshot"]["day"]),
            )
        ).one()
        PriceRepository(session).insert_bars([revised(bar)], actor="test:ingest")
        session.commit()
        assess(session, VALUED_AT)
        # Read now, without the stored system time, the cited fact and close have changed.
        who = subject(session, "AAPL")
        now = session.execute(select(func.now())).scalar_one()
        today = resolve(session, who, "financial_fact", fact_ref["ref"], WRITE_AT, now)
        assert today is not None and today.snapshot["value"] != fact_ref["snapshot"]["value"]
        close_now = resolve(session, who, "price_close", close_ref["ref"], WRITE_AT, now)
        assert (
            close_now is not None and close_now.snapshot["close"] != close_ref["snapshot"]["close"]
        )
        assert session.scalar(select(func.count()).select_from(ThesisCard)) == 3

    replayed = client.get(f"/journal/{card['card_id']}/replay", params={"version": 1}).json()
    assert replayed["identical"] is True, json.dumps(replayed, indent=2)[:3000]
    assert [e["status"] for e in replayed["evidence"]] == ["identical"] * 5
    assert replayed["valuation"]["status"] == "identical"
    assert [d["status"] for d in replayed["decisions"]] == ["identical"]
    trade = STATE["trade"]["card"]["card_id"]
    assert client.get(f"/journal/{trade}/replay").json()["identical"] is True


def fact_instrument(session: Session) -> UUID:
    return subject(session, "AAPL").instrument.id


def restated(fact: FinancialFact, value: Decimal, published_at: datetime) -> FinancialFactIn:
    return FinancialFactIn(
        entity_id=fact.entity_id,
        metric_id=fact.metric_id,
        value=value,
        unit=fact.unit,
        currency=fact.currency,
        fiscal_period=fact.fiscal_period,
        period_start=fact.period_start,
        period_end=fact.period_end,
        accession_id="0000320193-26-999999",
        provenance=provenance_of(fact, published_at),
    )


def provenance_of(row: FinancialFact | PriceBar, published_at: datetime) -> Provenance:
    return Provenance(
        source_id=row.source_id,
        source_tier=row.source_tier,
        source_url=row.source_url,
        published_at=published_at,
        published_at_precision="exact",
        ingested_at=datetime.now(UTC),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        as_of=row.as_of,
        license_status=row.license_status,  # type: ignore[arg-type]
        confidence=float(row.confidence),
        source_timezone=row.source_timezone,
    )


def revised(bar: PriceBar) -> BarIn:
    """The same session's close, corrected a minute after it was first published."""
    return BarIn(
        instrument_id=bar.instrument_id,
        symbol=bar.symbol,
        adjustment=bar.adjustment,
        bar_time=bar.bar_time,
        open=bar.open,
        high=bar.high + 1,
        low=bar.low,
        close=bar.close + 1,
        volume=bar.volume,
        vwap=bar.vwap,
        trade_count=bar.trade_count,
        feed=bar.feed,
        feed_status=bar.feed_status,
        provenance=provenance_of(bar, bar.published_at + timedelta(minutes=1)),
    )


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    card_id = STATE["trade"]["card"]["card_id"]
    at = {"known_at": iso(VALUED_AT)}
    for name, path, params in (
        ("journal", "/journal", at),
        ("journal-card", f"/journal/{card_id}", at),
        ("journal-replay", f"/journal/{card_id}/replay", {}),
        ("evidence-aapl", "/instruments/AAPL/evidence", {"known_at": iso(WRITE_AT)}),
        ("signals", "/signals", {"known_at": iso(VALUED_AT), "ticker": "AAPL"}),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded SEC filings, Alpaca closes, FRED yields and news replayed "
            "into the integration test database (tests/integration/test_journal.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_risk_web_fixtures(client: TestClient) -> None:
    # M2.3: the paper book with the AAPL TRADE open, and the risk checks (pass, veto, tried).
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    for name, path, params in (
        ("portfolio", "/portfolio", {"known_at": iso(WRITE_AT + timedelta(days=1))}),
        ("portfolio-empty", "/portfolio", {"known_at": iso(WRITE_AT - timedelta(days=1))}),
        ("risk-checks", "/risk/checks", {"limit": 10}),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded SEC filings, Alpaca closes, FRED yields and news replayed "
            "into the integration test database (tests/integration/test_journal.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
