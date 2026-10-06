"""M0.5b acceptance: the instrument API on recorded real SEC data (tests/fixtures/sec).

Apple: annual values match the filing they link to; "as known on" before the January 2010
10-K/A returns the original FY2008 net income. XOM: the predecessor Exxon Mobil Corp supplies
history and is the issuer before the 2026-07-01 reorganization (ADR-014).
Uses its own migrated database, so the ticker map does not collide with test_sec.py.
"""

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
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.sec.refresh import (
    company_ciks,
    filing_xbrl_candidates,
    universe_predecessors,
)
from autotrading.config_sync import load_sources, sync_sources
from autotrading.db.models import (
    AuditLog,
    EntityRelationship,
    Filing,
    FinancialFact,
    IngestionRun,
    Source,
)
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.settings import get_settings
from tests.integration.conftest import alembic_config
from tests.sec_replay import RECORDED_INSTANCES, recorded_registry, replay

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 2, tzinfo=UTC))
BEFORE_10KA = "2010-01-25T23:59:59+08:00"  # end of day SGT; the 10-K/A came 05:25 SGT next day
AFTER_10KA = "2010-01-27T23:59:59+08:00"
ORIGINAL_10K = "0001193125-09-214859"
RESTATED_10KA = "0001193125-10-012091"


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
        sync_sources(session, load_sources(get_settings().resolved_config_dir() / "sources.yaml"))
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    with Session(engine) as session:
        source = session.get_one(Source, "sec_edgar")
        source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    return sessionmaker(engine)


@pytest.fixture(scope="module")
def replayed(sessions: sessionmaker[Session]) -> Iterator[list[IngestionRun]]:
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    runner = IngestionRunner(
        sessions,
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        recorded_registry(),
    )
    run_ids = replay(runner, WINDOW, universe_predecessors(settings.resolved_config_dir()))
    with sessions() as session:
        yield [session.get_one(IngestionRun, run_id) for run_id in run_ids]
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def client(sessions: sessionmaker[Session], replayed: list[IngestionRun]) -> Iterator[TestClient]:
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        yield client


def fundamentals(client: TestClient, ticker: str, known_at: str | None = None) -> dict[str, Any]:
    params = {"known_at": known_at} if known_at else {}
    response = client.get(f"/instruments/{ticker}/fundamentals", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def row(table: dict[str, Any], metric_id: str) -> list[dict[str, Any] | None]:
    cells: list[dict[str, Any] | None] = next(
        r["cells"] for r in table["rows"] if r["metric_id"] == metric_id
    )
    return cells


def ends(table: dict[str, Any]) -> list[str]:
    return [p["period_end"] for p in table["periods"]]


# ---------- ingestion of the predecessor (ADR-014) ----------


def test_replay_ingests_both_xom_issuers(
    replayed: list[IngestionRun], sessions: sessionmaker[Session]
) -> None:
    # tickers, 4 companies (META included), filing XBRL of Apple and Meta (ADR-021)
    assert [(r.job, r.status) for r in replayed] == (
        [("sec.tickers", "succeeded")]
        + [("sec.company", "succeeded")] * 4
        + [("sec.filing_xbrl", "succeeded")] * 2
    )
    read = [f["accession"] for r in replayed[5:] for f in r.params["filings"]]
    assert sorted(read) == sorted(RECORDED_INSTANCES)
    with sessions() as session:
        assert company_ciks(session, ["XOM"]) == ["0000034088", "0002115436"]
        link = session.scalars(select(EntityRelationship)).one()
        assert link.evidence_accession == "0001193125-26-291990"
        assert link.effective_at == datetime(2026, 7, 1, 16, 36, 49, tzinfo=UTC)
        assert link.evidence_url.endswith("/000119312526291990/0001193125-26-291990-index.htm")
        audited = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.object_type == "entity_relationships", AuditLog.action == "insert")
        )
    assert audited == 1


def test_a_company_cannot_succeed_itself(engine: Engine, replayed: list[IngestionRun]) -> None:
    with Session(engine) as session:
        link = session.scalars(select(EntityRelationship)).one()
        link.successor_entity_id = link.predecessor_entity_id
        with pytest.raises(IntegrityError, match="distinct_entities"):
            session.commit()


# ---------- share counts tagged per class (ADR-021) ----------


def test_meta_share_counts_are_added_from_its_own_filing_xbrl(
    replayed: list[IngestionRun], sessions: sessionmaker[Session]
) -> None:
    meta_10k = "0001628280-26-003942"
    with sessions() as session:
        filing = session.scalars(select(Filing).where(Filing.accession_number == meta_10k)).one()
        facts = {
            (f.metric_id, f.period_end): f
            for f in session.scalars(
                select(FinancialFact).where(FinancialFact.accession_id == meta_10k)
            )
            if f.metric_id in ("shares_outstanding", "shares_outstanding_cover")
        }
        balance = facts[("shares_outstanding", date(2025, 12, 31))]
        cover = facts[("shares_outstanding_cover", date(2026, 1, 23))]
        assert (balance.value, cover.value) == (Decimal(2530000000), Decimal(2529555464))
        assert balance.source_concept == "us-gaap:CommonStockSharesOutstanding (sum of classes)"
        assert balance.published_at == filing.published_at  # the filing's stored acceptance
        assert balance.source_url == filing.source_url
        # Read once: a later refresh creates no run for the same filings.
        assert all(
            f.accession_number not in RECORDED_INSTANCES
            for f in filing_xbrl_candidates(session, "0001326801")
        )


# ---------- API ----------


def test_list_shows_universe_stocks_with_their_latest_report(client: TestClient) -> None:
    body = client.get("/instruments").json()
    by_ticker = {i["ticker"]: i for i in body["instruments"]}
    assert set(by_ticker) == {"AAPL", "XOM", "META"}
    assert (by_ticker["AAPL"]["cik"], by_ticker["AAPL"]["exchange"]) == ("0000320193", "XNAS")
    assert by_ticker["AAPL"]["latest_report"]["form"] == "10-Q"
    assert by_ticker["XOM"]["predecessors"] == ["Exxon Mobil Corp"]
    assert body["last_refresh_at"] is not None


def test_apple_values_link_to_the_filing_that_reported_them(client: TestClient) -> None:
    body = fundamentals(client, "aapl")  # tickers are case-insensitive
    assert body["ticker"] == "AAPL" and body["issuer"]["name"] == "Apple Inc."
    assert ends(body["annual"]) == ["2025-09-27", "2024-09-28", "2023-09-30"]
    revenue = row(body["annual"], "revenue")[0]
    assert revenue is not None
    assert (revenue["value"], revenue["unit"], revenue["period_start"]) == (
        "416161000000",
        "USD",
        "2024-09-29",
    )
    assert revenue["filing"] == {
        "accession": "0000320193-25-000079",
        "form": "10-K",
        "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
        "0000320193-25-000079-index.htm",
        "published_at": "2025-10-31T10:01:26Z",
        "published_at_precision": "exact",
    }
    assert (
        revenue["source_concept"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert ends(body["balance_sheet"])[0] == "2026-06-27"  # latest 10-Q balance sheet
    assert row(body["balance_sheet"], "cash")[0] is not None


def test_as_known_on_before_the_restatement_shows_the_original_value(client: TestClient) -> None:
    before = fundamentals(client, "AAPL", BEFORE_10KA)
    after = fundamentals(client, "AAPL", AFTER_10KA)
    assert ends(before["annual"]) == ["2009-09-26", "2008-09-27", "2007-09-29"]

    original = row(before["annual"], "net_income")[1]
    restated = row(after["annual"], "net_income")[1]
    assert original is not None and restated is not None
    assert (original["value"], original["restated"], original["filing"]["accession"]) == (
        "4834000000",
        False,
        ORIGINAL_10K,
    )
    assert (restated["value"], restated["restated"], restated["filing"]["form"]) == (
        "6119000000",
        True,
        "10-K/A",
    )
    assert restated["filing"]["accession"] == RESTATED_10KA
    assert restated["previous"]["value"] == "4834000000"
    assert restated["previous"]["filing"]["accession"] == ORIGINAL_10K


def test_xom_history_comes_from_the_predecessor(client: TestClient) -> None:
    now = fundamentals(client, "XOM")
    holdings, predecessor = now["entities"]
    assert (holdings["name"], holdings["role"]) == ("ExxonMobil Holdings Corp", "issuer")
    assert (predecessor["name"], predecessor["role"], predecessor["cik"]) == (
        "Exxon Mobil Corp",
        "predecessor",
        "0000034088",
    )
    assert predecessor["evidence_accession"] == "0001193125-26-291990"
    assert now["issuer"]["id"] == holdings["id"]

    # Fiscal years were reported by Exxon Mobil Corp; the holding company has filed one 10-Q.
    assert ends(now["annual"]) == ["2025-12-31", "2024-12-31", "2023-12-31"]
    revenue = [c for c in row(now["annual"], "revenue") if c is not None]
    assert len(revenue) == 3 and {c["reported_by"] for c in revenue} == {predecessor["id"]}
    # The latest balance sheet is the holding company's own.
    cash = row(now["balance_sheet"], "cash")[0]
    assert ends(now["balance_sheet"])[0] == "2026-06-30"
    assert cash is not None and cash["reported_by"] == holdings["id"]


def test_before_the_reorganization_the_issuer_was_exxon_mobil_corp(client: TestClient) -> None:
    before = fundamentals(client, "XOM", "2026-06-01T00:00:00Z")
    assert before["issuer"]["name"] == "Exxon Mobil Corp"
    assert ends(before["balance_sheet"])[0] == "2026-03-31"  # Q1 10-Q, before the holding co.


def test_unknown_ticker_is_404(client: TestClient) -> None:
    assert client.get("/instruments/NOPE/fundamentals").status_code == 404


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    for name, path, params in (
        ("instruments", "/instruments", {}),
        ("fundamentals-aapl", "/instruments/AAPL/fundamentals", {}),
        (
            "fundamentals-aapl-before-10ka",
            "/instruments/AAPL/fundamentals",
            {"known_at": BEFORE_10KA},
        ),
        (
            "fundamentals-aapl-after-10ka",
            "/instruments/AAPL/fundamentals",
            {"known_at": AFTER_10KA},
        ),
        ("fundamentals-xom", "/instruments/XOM/fundamentals", {}),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded SEC fixtures replayed into the integration test database "
            "(tests/integration/test_instruments.py)",
            "endpoint": path,
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
