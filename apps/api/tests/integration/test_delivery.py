"""Alert delivery to Telegram (M3.0b, ADR-037) against a migrated database and a fake sender:
which alerts are pushed, each sent once and recorded, failures tried again up to the limit,
quiet hours, the audit trail, and no chat id or token anywhere in the ledger."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.telegram.client import TelegramError
from autotrading.config_sync import (
    load_delivery_rules,
    sync_alert_rules,
    sync_delivery_rules,
)
from autotrading.db.models import Alert, AlertDelivery, DigestDelivery
from autotrading.domain.convergence import AlertIn
from autotrading.main import create_app
from autotrading.repositories.convergence import insert_alert, load_alert_rules, stored_alert_rules
from autotrading.repositories.delivery import (
    deliver,
    deliver_digest,
    delivered,
    pending,
    stored_delivery_rules,
)
from autotrading.settings import get_settings
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

CONFIG = get_settings().resolved_config_dir()
NOW = datetime(2026, 10, 20, 3, 20, tzinfo=UTC)  # 11:20 Singapore time
CHAT = "987654321"


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    with Session(engine) as session:
        sync_alert_rules(session, load_alert_rules())
        sync_delivery_rules(session, load_delivery_rules(CONFIG / "delivery_rules.yaml"))
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


def market_alert(
    session: Session,
    key: str,
    kind: str = "regime",
    ago: timedelta = timedelta(minutes=5),
    backfilled: bool = False,
) -> Alert:
    rules = stored_alert_rules(session)
    assert rules is not None
    at = NOW - ago
    alert = AlertIn(
        kind=kind,  # type: ignore[arg-type]
        level=2,
        previous_level=1,
        direction="up",
        title=f"Test {kind} {key}",
        source_key=f"{kind}:{key}",
        known_at=at,
        evidence=[{"table": "regime_assessments", "id": key, "label": f"flag {key}"}],
    )
    assert insert_alert(session, rules, None, None, alert, at, None, backfilled)
    return session.scalars(select(Alert).where(Alert.source_key == alert.source_key)).one()


def ledger(session: Session) -> list[AlertDelivery]:
    return list(session.scalars(select(AlertDelivery).order_by(AlertDelivery.attempted_at)))


def test_each_pushed_alert_is_sent_once_and_recorded(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        rules = stored_delivery_rules(session)
        assert rules is not None
        regime = market_alert(session, "r1")
        s4 = market_alert(session, "m1", kind="momentum", ago=timedelta(minutes=4))
        market_alert(session, "b1", backfilled=True)  # backfilled: never pushed
        market_alert(session, "o1", ago=timedelta(hours=60))  # older than 48 hours
        session.commit()
        sent: list[str] = []

        def send(message: str) -> int:
            sent.append(message)
            return 100 + len(sent)

        assert deliver(session, rules, send, NOW) == (2, 0)
        # delivery rules 0.2.0: Chinese; these test rows have no assessment behind them, so the
        # messages fall back to their titles and evidence (ADR-038)
        assert [m.split("\n")[0] for m in sent] == [
            "[autotrading] 市場壓力｜升到高（原升高）",
            "[autotrading] S4 動能｜每月目標調整",
        ]
        assert "Test regime r1" in sent[0] and "依據：flag r1" in sent[0]
        assert all(m.endswith("不是投資建議；僅供模擬（Paper only）。") for m in sent)
        rows = ledger(session)
        assert [(r.alert_id, r.status, r.message_id) for r in rows] == [
            (regime.id, "sent", 101),
            (s4.id, "sent", 102),
        ]
        assert all((r.channel, r.rule_version) == ("telegram", "0.4.0") for r in rows)
        # a second run sends nothing more
        assert deliver(session, rules, send, NOW + timedelta(minutes=5)) == (0, 0)
        assert set(delivered(session, [regime.id, s4.id])) == {regime.id, s4.id}
        # the ledger holds no chat id, and the rows are audited by the delivery actor
        assert CHAT not in str([(r.error, r.message_id) for r in rows])
        actors = session.execute(
            text("SELECT DISTINCT actor FROM audit_log WHERE object_type = 'alert_deliveries'")
        ).scalars()
        assert set(actors) == {"delivery:telegram"}


def test_a_failure_is_recorded_and_tried_again_up_to_the_limit(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        rules = stored_delivery_rules(session)
        assert rules is not None
        failing = market_alert(session, "f1", kind="rotation")
        session.commit()

        def refuse(_: str) -> int:
            raise TelegramError("sendMessage: Bad Request: chat not found", 400)

        for run in range(rules.max_attempts):
            assert deliver(session, rules, refuse, NOW + timedelta(minutes=run)) == (0, 1)
        # no attempt left: no longer pending, nothing sent
        assert failing.id not in {a.id for a in pending(session, rules, NOW)}
        tries = [r for r in ledger(session) if r.alert_id == failing.id]
        assert [(r.status, r.error_code) for r in tries] == [("failed", 400)] * 3
        assert tries[0].error == "sendMessage: Bad Request: chat not found"


def test_quiet_hours_wait_and_the_database_allows_one_sent_row(
    sessions: sessionmaker[Session], engine: Engine
) -> None:
    with sessions() as session:
        rules = stored_delivery_rules(session)
        assert rules is not None
        waiting = market_alert(session, "q1", kind="portfolio")
        session.commit()
        night = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)  # 00:00 Singapore time
        assert deliver(session, rules, lambda _: 1, night) == (0, 0)
        assert waiting.id in {a.id for a in pending(session, rules, night)}
        morning = datetime(2026, 10, 20, 23, 30, tzinfo=UTC)  # 07:30
        assert deliver(session, rules, lambda _: 7, morning) == (1, 0)
        waiting_id = waiting.id
    with engine.connect() as conn, pytest.raises(Exception, match="uq_alert_deliveries_sent"):
        conn.execute(
            text(
                "INSERT INTO alert_deliveries (alert_id, channel, rule_version, status, "
                "message_id) VALUES (:id, 'telegram', '0.2.0', 'sent', 8)"
            ),
            {"id": waiting_id},
        )


def test_the_weekly_digest_is_sent_once_a_week_and_recorded(
    sessions: sessionmaker[Session],
) -> None:
    monday = datetime(2026, 10, 19, 0, 10, tzinfo=UTC)  # 08:10 Singapore time
    with sessions() as session:
        rules = stored_delivery_rules(session)
        assert rules is not None and rules.digest is not None
        sent: list[str] = []

        def send(text: str) -> int:
            sent.append(text)
            return 500 + len(sent)

        def refuse(_: str) -> int:
            raise TelegramError("sendMessage: Too Many Requests", 429)

        assert deliver_digest(session, rules, refuse, monday) == 0  # failed, recorded
        assert deliver_digest(session, rules, send, monday + timedelta(hours=2)) == 0  # not due
        assert deliver_digest(session, rules, send, monday) >= 1
        assert sent[0].startswith("[autotrading] 每週規則候選（模擬，非建議）｜2026-10-19 這週")
        assert "（目前沒有）" in sent[0]  # no candidate in this database
        assert deliver_digest(session, rules, send, monday, force=True) == 0  # once a week
        rows = session.scalars(select(DigestDelivery).order_by(DigestDelivery.attempted_at)).all()
        assert [(r.status, r.error_code, r.week) for r in rows] == [
            ("failed", 429, monday.date()),
            ("sent", None, monday.date()),
        ]
        assert rows[1].message_id == 501 and CHAT not in str([r.error for r in rows])


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


@pytest.mark.parametrize("configured", [False, True])
def test_the_alerts_api_says_whether_telegram_is_on_and_what_was_sent(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    monkeypatch.setattr("autotrading.api.alerts.telegram.configured", lambda: configured)
    with sessions() as session:
        sent = {r.alert_id for r in ledger(session) if r.status == "sent"}
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        body = client.get(
            "/alerts", params={"status": "all", "known_at": "2026-10-21T00:00:00Z"}
        ).json()
    delivery = body["delivery"]
    assert (delivery["channel"], delivery["configured"], delivery["rule_version"]) == (
        "telegram",
        configured,
        "0.4.0",
    )
    assert delivery["detail"].startswith("Telegram on" if configured else "Telegram not set up")
    assert CHAT not in str(body)
    pushed = {e["id"] for e in body["entries"] if e["delivered_at"]}
    assert pushed == {str(i) for i in sent} and pushed
    assert body["open_by_level"] == {}  # market alerts are not convergence levels


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("autotrading.api.alerts.telegram.configured", lambda: True)
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    params = {"status": "all", "known_at": "2026-10-21T00:00:00Z"}
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        response = client.get("/alerts", params=params)
    assert response.status_code == 200
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "recorded_from": "test market alerts pushed through a fake Telegram sender in the "
        "integration test database (tests/integration/test_delivery.py)",
        "endpoint": "/alerts",
        "params": params,
        "response": response.json(),
    }
    (target / "alerts-delivered.json").write_text(json.dumps(record, indent=2) + "\n")
