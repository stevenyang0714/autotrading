"""Real holdings API (M3.10, ADR-041 H8, H13) on its own database: entries in, the valuation at a
pinned T with closes, a TWD rate and the change, reversals, the entry list, the audit actor and a
snapshot that recomputes identically. Trade dates are October 2026, before any run of this test;
the system time is always the database's."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.alpaca import refresh as alpaca_refresh
from autotrading.config_sync import load_sources, sync_sources
from autotrading.db.models import (
    AuditLog,
    HoldingEntry,
    Identifier,
    Instrument,
    MacroSeries,
    Source,
)
from autotrading.domain.macro import MacroObservationIn
from autotrading.domain.markets import TW, US
from autotrading.main import create_app
from autotrading.repositories.holdings import recompute, record_snapshot, tracked
from autotrading.repositories.macro import MacroObservationRepository
from autotrading.repositories.prices import BarIn, PriceRepository
from tests.factories import TEST_SOURCE_ID, provenance
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

CONFIG = Path(__file__).resolve().parents[4] / "config"
T = datetime(2026, 10, 27, 3, 12, tzinfo=UTC)  # 11:12 Singapore
STATE: dict[str, Any] = {}
OCT_22_NY_CLOSE = datetime(2026, 10, 22, 21, tzinfo=UTC)
OCT_23_NY_CLOSE = datetime(2026, 10, 24, tzinfo=UTC)
OCT_22_TWSE_FILE = datetime(2026, 10, 22, 21, 20, tzinfo=UTC)  # 05:20 Taipei the next morning


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


def _instrument(session: Session, symbol: str, namespace: str, currency: str, mic: str) -> UUID:
    instrument = Instrument(instrument_type="equity", primary_exchange=mic, currency=currency)
    session.add(instrument)
    session.flush()
    session.add(
        Identifier(
            instrument_id=instrument.id,
            id_type="ticker",
            id_namespace=namespace,
            id_value=symbol,
            valid_from=datetime(2016, 1, 1, tzinfo=UTC),
            source_id="twse_openapi" if namespace == TW.namespace else "alpaca_iex",
        )
    )
    session.flush()
    return instrument.id


def _bar(instrument_id: UUID, symbol: str, day: date, close: str, published: datetime) -> BarIn:
    price = Decimal(close)
    return BarIn(
        instrument_id=instrument_id,
        symbol=symbol,
        adjustment="raw",
        bar_time=published - timedelta(hours=4),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1000,
        vwap=None,
        trade_count=None,
        feed="sip",
        feed_status="fixture",
        provenance=provenance(
            source_url="https://example.com/bars",
            published_at=published,
            ingested_at=published,
            effective_from=published,
            effective_to=None,
            as_of=published,
        ),
        bar_date=day,
    )


def _rate(day: date, value: str, published: datetime) -> MacroObservationIn:
    return MacroObservationIn(
        series_id="DEXTAUS",
        observation_date=day,
        value=Decimal(value),
        vintage=published.date(),
        provenance=provenance(
            source_url="https://fred.stlouisfed.org/series/DEXTAUS",
            published_at=published,
            ingested_at=published,
            effective_from=published,
            effective_to=None,
            as_of=published,
        ),
    )


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    with Session(engine) as session:
        sync_sources(session, load_sources(CONFIG / "sources.yaml"))
        session.add(
            Source(
                id=TEST_SOURCE_ID,
                name="Test source",
                url="https://example.com",
                tier=1,
                license_status="public",
                update_cadence="daily",
                freshness_sla_seconds=86400,
            )
        )
        session.add(
            MacroSeries(id="DEXTAUS", term_id="macro_twd_usd", source_id="fred", position=180)
        )
        spy = _instrument(session, "SPY", US.namespace, "USD", "ARCX")
        tsmc = _instrument(session, "2330", TW.namespace, "TWD", "XTAI")
        PriceRepository(session).insert_bars(
            [
                _bar(spy, "SPY", date(2026, 10, 22), "600", OCT_22_NY_CLOSE),
                _bar(spy, "SPY", date(2026, 10, 23), "610", OCT_23_NY_CLOSE),
                _bar(tsmc, "2330", date(2026, 10, 22), "1500", OCT_22_TWSE_FILE),
            ],
            actor="test",
        )
        MacroObservationRepository(session).insert_many(
            [
                _rate(date(2026, 10, 16), "32.00", datetime(2026, 10, 19, 21, tzinfo=UTC)),
                _rate(date(2026, 10, 23), "32.10", datetime(2026, 10, 26, 21, tzinfo=UTC)),
            ],
            actor="test",
        )
        session.commit()
        STATE.update(spy=spy, tsmc=tsmc)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


@pytest.fixture(scope="module")
def client(sessions: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app(health_checker=OkChecker(), sessions=sessions)
    with TestClient(app) as client:
        yield client


def cents(value: Fraction) -> Decimal:
    return round(Decimal(value.numerator) / value.denominator, 2)


def post(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/holdings/entries", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.fixture(scope="module")
def ledger(client: TestClient) -> dict[str, dict[str, Any]]:
    usd = {"account": "Firstrade"}
    twd = {"account": "元大"}
    return {
        "deposit_usd": post(
            client, kind="deposit", currency="USD", amount="10000", trade_date="2026-10-01", **usd
        ),
        "buy_spy": post(
            client,
            kind="buy",
            market="US",
            symbol="spy",
            quantity="10",
            price="580",
            fee="1",
            trade_date="2026-10-20",
            **usd,
        ),
        "deposit_twd": post(
            client, kind="deposit", currency="TWD", amount="200000", trade_date="2026-10-01", **twd
        ),
        "buy_tsmc": post(
            client,
            kind="buy",
            market="TW",
            symbol="2330",
            quantity="100",
            price="1450",
            fee="20",
            trade_date="2026-10-21",
            note="第一筆",
            **twd,
        ),
        "sell_spy": post(
            client,
            kind="sell",
            market="US",
            symbol="SPY",
            quantity="4",
            price="605",
            trade_date="2026-10-23",
            **usd,
        ),
    }


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        ({"broker": "alpaca"}, 422, "extra"),
        ({"symbol": "2330"}, 422, "not a US symbol"),
        ({"symbol": "BRK-B"}, 422, "not a US symbol"),  # Alpaca writes BRK.B
        ({"trade_date": "2099-01-01"}, 422, "after today"),
        ({"quantity": "500", "kind": "sell"}, 422, "short"),
        ({"amount": "5"}, 422, "a trade not"),
        ({"price": "0"}, 422, "greater than 0"),
        ({"kind": "deposit"}, 422, "is cash"),
    ],
)
def test_entries_are_validated(
    client: TestClient,
    ledger: dict[str, dict[str, Any]],
    body: dict[str, Any],
    status: int,
    detail: str,
) -> None:
    base = {
        "kind": "buy",
        "account": "Firstrade",
        "market": "US",
        "symbol": "SPY",
        "quantity": "1",
        "price": "600",
        "trade_date": "2026-10-22",
    }
    response = client.post("/holdings/entries", json={**base, **body})
    assert response.status_code == status
    assert detail in response.text


def test_the_valuation_at_t(client: TestClient, ledger: dict[str, dict[str, Any]]) -> None:
    body = client.get("/holdings", params={"known_at": T.isoformat()}).json()
    by_symbol = {p["symbol"]: p for p in body["positions"]}
    spy, tsmc = by_symbol["SPY"], by_symbol["2330"]
    assert (spy["quantity"], spy["average_cost"], spy["realized"]) == (
        "6.000000",
        "580.000000",
        "100.00",
    )
    assert (spy["mark"]["session"], spy["market_value"], spy["unrealized"]) == (
        "2026-10-23",
        "3660.00",
        "180.00",
    )
    assert (spy["research"], tsmc["research"]) == (False, True)  # SPY: a universe ETF, no page
    assert (tsmc["market_value"], tsmc["unrealized"], tsmc["currency"]) == (
        "150000.00",
        "5000.00",
        "TWD",
    )
    cash = {c["currency"]: c["balance"] for c in body["cash"]}
    assert cash == {"USD": "6619.00", "TWD": "54980.00"}  # 10000-5801+2420; 200000-145020
    assert body["fx"]["value"] == "32.10" and body["fx"]["observation_date"] == "2026-10-23"
    assert body["fx"]["lag_days"] == 3 and body["fx"]["stale"] is False
    # USD 3660 + 6619; TWD 150000 + 54980 at 32.10 per USD.
    assert Decimal(body["equity_usd"]) == cents(
        Fraction(10279) + Fraction(204980) / Fraction("32.10")
    )
    # The day before, the 10-23 rate was not yet public (H.10 publishes on Mondays): 32.00.
    before = cents(Fraction(10279) + Fraction(204980) / Fraction("32.00"))
    assert Decimal(body["change_usd"]) == Decimal(body["equity_usd"]) - before
    assert body["flags"] == [] and body["entries"] == 5
    assert body["valuation_version"] == "0.1.0" and body["base_currency"] == "USD"


def test_a_reversal_undoes_the_entry_once(
    client: TestClient, ledger: dict[str, dict[str, Any]]
) -> None:
    sell = ledger["sell_spy"]["id"]
    response = client.post(f"/holdings/entries/{sell}/reverse", json={"note": "wrong day"})
    assert response.status_code == 201
    reversal = response.json()
    assert (reversal["kind"], reversal["reverses_id"], reversal["status"]) == (
        "reversal",
        sell,
        "reversal",
    )
    assert client.post(f"/holdings/entries/{sell}/reverse", json={}).status_code == 409
    assert client.post(f"/holdings/entries/{reversal['id']}/reverse", json={}).status_code == 409
    missing = client.post(f"/holdings/entries/{UUID(int=1)}/reverse", json={})
    assert missing.status_code == 404
    body = client.get("/holdings", params={"known_at": T.isoformat()}).json()
    spy = next(p for p in body["positions"] if p["symbol"] == "SPY")
    assert spy["quantity"] == "10.000000" and spy["realized"] == "0.00"
    listed = client.get("/holdings/entries").json()
    status = {e["id"]: e["status"] for e in listed["entries"]}
    assert status[sell] == "reversed" and status[reversal["id"]] == "reversal"
    assert status[ledger["buy_spy"]["id"]] == "counted"
    assert listed["accounts"] == ["Firstrade", "元大"]
    assert listed["entries"][0]["id"] == reversal["id"]  # newest first


def test_entries_are_audited_as_web(
    sessions: sessionmaker[Session], ledger: dict[str, dict[str, Any]]
) -> None:
    ids = [entry["id"] for entry in ledger.values()]
    with sessions() as session:
        actors = set(
            session.scalars(
                select(AuditLog.actor).where(
                    AuditLog.object_type == "holding_entries", AuditLog.object_id.in_(ids)
                )
            )
        )
        stored = session.scalar(select(func.count()).select_from(HoldingEntry))
    assert actors == {"web"} and stored is not None and stored >= 5


def test_a_snapshot_recomputes_identically(
    sessions: sessionmaker[Session], ledger: dict[str, dict[str, Any]]
) -> None:
    with sessions() as session:
        now = session.execute(select(func.now())).scalar_one()
        assert record_snapshot(session, T, datetime(2026, 1, 1, tzinfo=UTC), "manual") is None
        snapshot = record_snapshot(session, T, now, "manual")
        session.commit()
        assert snapshot is not None
        assert snapshot.positions == 2 and snapshot.cash.keys() == {"USD", "TWD"}
        assert recompute(session, snapshot) == snapshot.holdings
        assert snapshot.holdings["equity_usd"] == str(snapshot.equity_usd)


class FakeRunner:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.created: list[tuple[str, dict[str, Any]]] = []

    def create_run(self, name: str, params: dict[str, Any], window: object) -> UUID:
        self.created.append((name, params))
        return UUID(int=len(self.created))


def test_a_listing_outside_the_universe_becomes_tracked(
    client: TestClient,
    sessions: sessionmaker[Session],
    ledger: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # H5, H6: the first entry of ZZZZ (US) and 2603 (TWSE) creates tracked instruments; the daily
    # runs then fetch their closes. Until then each is valued at cost and flagged.
    buy = {"kind": "buy", "quantity": "2", "price": "50", "trade_date": "2026-10-09"}
    post(client, account="Firstrade", market="US", symbol="ZZZZ", **buy)
    post(client, account="元大", market="TW", symbol="2603", **{**buy, "price": "250"})
    with sessions() as session:
        made = {
            row.id_value: (row.id_namespace, row.source_id, instrument.instrument_type)
            for row, instrument in session.execute(
                select(Identifier, Instrument)
                .join(Instrument, Instrument.id == Identifier.instrument_id)
                .where(Identifier.id_value.in_(["ZZZZ", "2603"]))
            )
        }
        assert made == {
            "ZZZZ": ("alpaca", "alpaca_iex", "other"),
            "2603": ("twse", "twse_openapi", "other"),
        }
        assert tracked(session, "US") == (["ZZZZ"], date(2026, 10, 9))  # SPY is the universe's
        assert tracked(session, "TW") == (["2603"], date(2026, 10, 9))
    body = client.get("/holdings", params={"known_at": T.isoformat()}).json()
    zzzz = next(p for p in body["positions"] if p["symbol"] == "ZZZZ")
    assert (zzzz["flags"], zzzz["market_value"], zzzz["name"]) == (["no_mark"], "100.00", None)

    monkeypatch.setattr(alpaca_refresh, "source_ready", lambda session: True)
    runner = FakeRunner(sessions)
    alpaca_refresh.start_tracked(
        runner,  # type: ignore[arg-type]
        now=T,
        manual=False,
        symbols=["ZZZZ"],
        since=date(2026, 10, 9),
    )
    assert runner.created == [
        ("alpaca.daily_bars", {"symbols": ["ZZZZ"], "etfs": [], "start": "2026-10-06"}),
        ("alpaca.splits", {"symbols": ["ZZZZ"], "start": "2016-01-01"}),
    ]
    assert (
        alpaca_refresh.start_tracked(
            runner,  # type: ignore[arg-type]
            now=T,
            manual=False,
            symbols=[],
            since=None,
        )
        == []
    )


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient, ledger: dict[str, dict[str, Any]]) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    recorded: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("holdings", "/holdings", {"known_at": T.isoformat()}),
        ("holdings-entries", "/holdings/entries", {}),
    )
    for name, path, params in recorded:
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "a made-up ledger, closes and DEXTAUS rates in the integration test "
            "database (tests/integration/test_holdings_api.py); no real holdings",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n"
        )
