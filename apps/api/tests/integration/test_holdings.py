"""Real holdings (M3.10, ADR-041): the ledger and snapshot tables, each kind's fields, append-only
rows, reversals and the audit actor. Runs against a throwaway database (see conftest)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from autotrading.db.models import AuditLog, HoldingEntry, HoldingSnapshot, Instrument
from autotrading.repositories.audit import set_actor

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def spy(engine: Engine) -> UUID:
    with Session(engine) as session:
        instrument = Instrument(instrument_type="etf", primary_exchange="ARCX", currency="USD")
        session.add(instrument)
        session.commit()
        return instrument.id


def buy(spy: UUID, **fields: Any) -> HoldingEntry:
    values: dict[str, Any] = {
        "kind": "buy",
        "account": "Firstrade",
        "market": "US",
        "instrument_id": spy,
        "symbol": "SPY",
        "currency": "USD",
        "trade_date": date(2026, 10, 2),
        "quantity": Decimal(10),
        "price": Decimal("580.25"),
        "fee": Decimal(0),
        "user_id": "steven",
    }
    return HoldingEntry(**{**values, **fields})


def save(engine: Engine, row: HoldingEntry) -> HoldingEntry:
    with Session(engine, expire_on_commit=False) as session:
        set_actor(session, "web")
        session.add(row)
        session.commit()
        return row


@pytest.mark.parametrize(
    ("fields", "check"),
    [
        ({"currency": "TWD"}, "market_currency"),
        ({"market": "TW"}, "market_currency"),
        ({"quantity": Decimal(0)}, "kind_fields"),
        ({"price": None}, "kind_fields"),  # a NULL never passes as positive
        ({"quantity": None}, "kind_fields"),
        (
            {
                "kind": "deposit",
                "market": None,
                "instrument_id": None,
                "symbol": None,
                "quantity": None,
                "price": None,
                "fee": None,
            },
            "kind_fields",
        ),  # a deposit needs its amount
        ({"amount": Decimal(1)}, "kind_fields"),
        ({"kind": "deposit"}, "kind_fields"),  # a deposit carries no instrument
        ({"kind": "dividend"}, "kind_fields"),  # a dividend is an amount, not shares
        ({"kind": "reversal"}, "kind_fields"),
        ({"symbol": "spy"}, "symbol_format"),
        ({"account": ""}, "account_length"),
        ({"note": "x" * 501}, "note_length"),
        ({"trade_date": date(2099, 1, 1)}, "trade_date_not_future"),
        ({"user_id": "someone"}, "single_user"),
        ({"kind": "short"}, "ck_holding_entries_kind"),
    ],
)
def test_each_kind_carries_only_its_fields(
    engine: Engine, spy: UUID, fields: dict[str, Any], check: str
) -> None:
    with pytest.raises(IntegrityError, match=check):
        save(engine, buy(spy, **fields))


def test_cash_entries_and_a_reversal_are_audited_as_web(engine: Engine, spy: UUID) -> None:
    deposit = save(
        engine,
        HoldingEntry(
            kind="deposit",
            account="Firstrade",
            currency="USD",
            trade_date=date(2026, 10, 1),
            amount=Decimal(10000),
            user_id="steven",
        ),
    )
    trade = save(engine, buy(spy))
    fix = save(
        engine,
        HoldingEntry(
            kind="reversal",
            account="Firstrade",
            currency="USD",
            trade_date=trade.trade_date,
            reverses_id=trade.id,
            user_id="steven",
        ),
    )
    with pytest.raises(IntegrityError, match="uq_holding_entries_reverses_id"):
        save(
            engine,
            HoldingEntry(
                kind="reversal",
                account="Firstrade",
                currency="USD",
                trade_date=trade.trade_date,
                reverses_id=trade.id,
                user_id="steven",
            ),
        )
    with Session(engine) as session:
        audited = session.scalars(
            select(AuditLog.actor).where(
                AuditLog.object_type == "holding_entries",
                AuditLog.object_id.in_([str(deposit.id), str(trade.id), str(fix.id)]),
            )
        ).all()
    assert audited == ["web", "web", "web"]


def test_entries_and_snapshots_are_append_only(engine: Engine, spy: UUID) -> None:
    save(engine, buy(spy))
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(
            HoldingSnapshot(
                known_at=now - timedelta(minutes=1),
                system_time=now,
                valuation_version="0.1.0",
                equity_usd=None,
                cash={},
                fx=None,
                positions=0,
                holdings={},
                trigger="manual",
            )
        )
        session.commit()
    for statement in (
        "UPDATE holding_entries SET quantity = 1",
        "DELETE FROM holding_entries",
        "UPDATE holding_snapshots SET equity_usd = 1",
        "DELETE FROM holding_snapshots",
    ):
        with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text(statement))
    for table in ("holding_entries", "holding_snapshots"):
        with engine.connect() as conn, pytest.raises(DBAPIError, match="TRUNCATE"):
            conn.execute(text(f"TRUNCATE {table}"))
