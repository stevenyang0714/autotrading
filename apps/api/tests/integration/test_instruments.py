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
from itertools import pairwise
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

from autotrading.adapters.sec import reconcile
from autotrading.adapters.sec.instance import parse_instance
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
    FilingReconciliation,
    FinancialFact,
    IngestionRun,
    ReconciliationItem,
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
from tests import alpaca_replay
from tests.integration.conftest import alembic_config
from tests.sec_replay import FIXTURES, RECORDED_INSTANCES, recorded_registry, replay

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
        alpaca_replay.register_recorded(recorded_registry(), fixture=False),
    )
    # Splits (since 2016, and the reviewed earlier ones) before the filing XBRL, as production.
    run_ids = replay(
        runner,
        WINDOW,
        universe_predecessors(settings.resolved_config_dir()),
        before_instances=lambda: alpaca_replay.replay_splits(runner, WINDOW),
    )
    # One year of end-of-day closes for valuation (M1.2), labelled as the real job stores them.
    bars = runner.create_run(
        "alpaca.daily_bars", alpaca_replay.recorded_params("alpaca.daily_bars"), WINDOW
    )
    runner.execute(bars)
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
    # tickers, 4 companies (META included), splits, filing XBRL of Apple and Meta (ADR-021)
    assert [(r.job, r.status) for r in replayed] == (
        [("sec.tickers", "succeeded")]
        + [("sec.company", "succeeded")] * 4
        + [("alpaca.splits", "succeeded")]
        + [("sec.filing_xbrl", "succeeded")] * 2
    )
    read = [f["accession"] for r in replayed[6:] for f in r.params["filings"]]
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
        # Read once: a later refresh reads only the filings not read yet, plus the latest 10-K
        # to confirm the share classes while other class sums are due.
        again = {f.accession_number for f in filing_xbrl_candidates(session, "0001326801")}
        assert again & RECORDED_INSTANCES == {meta_10k}


# ---------- split-adjusted per-share history (ADR-021) ----------


def test_apple_per_share_history_is_continuous_across_the_2020_split(client: TestClient) -> None:
    body = fundamentals(client, "AAPL", "2026-10-06T00:00:00Z")
    assert [(s["ex_date"], s["new_rate"]) for s in body["splits"]] == [
        ("2014-06-09", "7"),
        ("2020-08-31", "4"),
    ]
    history = body["per_share_history"]
    years = ends(history)
    eps = dict(zip(years, row(history, "eps_diluted"), strict=True))
    fy2017 = eps["2017-09-30"]
    assert fy2017 is not None
    # As reported (first in the FY2017 10-K, before the split), the adjusted value beside it.
    assert (fy2017["value"], fy2017["filing"]["accession"]) == ("9.21", "0000320193-17-000070")
    assert fy2017["split_adjusted"] == {"value": "2.3025", "factor": "4", "splits": ["2020-08-31"]}
    fy2018 = eps["2018-09-29"]
    assert fy2018 is not None and fy2018["split_adjusted"] is None  # restated by Apple already
    shown = [
        Decimal(c["split_adjusted"]["value"] if c["split_adjusted"] else c["value"])
        for c in (eps[y] for y in sorted(years))
        if c is not None
    ]
    assert len(shown) >= 10
    # No step of a split's size between consecutive years.
    assert all(Decimal("0.5") < b / a < Decimal(2) for a, b in pairwise(shown))


def test_before_the_split_was_effective_nothing_is_adjusted(client: TestClient) -> None:
    body = fundamentals(client, "AAPL", "2020-08-30T00:00:00Z")
    assert [s["ex_date"] for s in body["splits"]] == ["2014-06-09"]
    eps = dict(
        zip(
            ends(body["per_share_history"]),
            row(body["per_share_history"], "eps_diluted"),
            strict=True,
        )
    )
    fy2019 = eps["2019-09-28"]
    assert fy2019 is not None
    assert (fy2019["value"], fy2019["split_adjusted"]) == ("11.89", None)


# ---------- derived values and quarters (ADR-021) ----------


def test_fcf_and_debt_exist_exactly_where_their_inputs_do(client: TestClient) -> None:
    for ticker in ("AAPL", "XOM", "META"):
        body = fundamentals(client, ticker)
        annual, balance = body["annual"], body["balance_sheet"]
        ocf, capex, fcf = (
            row(annual, m) for m in ("operating_cash_flow", "capex", "free_cash_flow")
        )
        for o, c, f in zip(ocf, capex, fcf, strict=True):
            assert (f is not None) == (o is not None and c is not None)
            if f is not None and o is not None and c is not None:
                assert Decimal(f["value"]) == Decimal(o["value"]) - Decimal(c["value"])
                assert [i["metric_id"] for i in f["inputs"]] == ["operating_cash_flow", "capex"]
        noncurrent, debt, net, cash = (
            row(balance, m) for m in ("long_term_debt_noncurrent", "total_debt", "net_debt", "cash")
        )
        for n, d, nd, c in zip(noncurrent, debt, net, cash, strict=True):
            assert (d is not None) == (n is not None)
            assert (nd is not None) == (n is not None and c is not None)


def test_meta_total_debt_says_which_short_items_were_not_reported(client: TestClient) -> None:
    balance = fundamentals(client, "META")["balance_sheet"]
    latest = row(balance, "total_debt")[0]
    assert latest is not None and latest["kind"] == "derived"
    zero = [i["metric_id"] for i in latest["inputs"] if i["assumed_zero"]]
    assert "commercial_paper" in zero  # Meta has no commercial paper
    assert Decimal(latest["value"]) == sum(
        Decimal(i["value"]) for i in latest["inputs"] if not i["assumed_zero"]
    )


def test_apple_quarters_add_up_to_the_year_and_match_reported_quarters(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    body = fundamentals(client, "AAPL", "2026-08-01T00:00:00Z")
    quarterly = body["quarterly"]
    revenue = next(r for r in quarterly["rows"] if r["metric_id"] == "revenue")
    fy2025 = [
        c for c in revenue["cells"] if c and "2024-09-29" <= c["period_start"] <= "2025-09-27"
    ]
    year = next(c for c in row(body["annual"], "revenue") if c and c["period_end"] == "2025-09-27")
    assert len(fy2025) == 4
    assert sum(Decimal(c["value"]) for c in fy2025) == Decimal(year["value"])
    assert [c["method"] for c in fy2025] == [
        "reported",
        "ytd_difference",
        "ytd_difference",
        "year_minus_9_months",
    ]
    # Differenced quarters equal the three-month revenue Apple reports in its 10-Qs.
    with sessions() as session:
        reported = {
            (f.period_start.isoformat(), f.period_end.isoformat()): f.value
            for f in session.scalars(
                select(FinancialFact).where(
                    FinancialFact.metric_id == "revenue",
                    FinancialFact.superseded_at.is_(None),
                )
            )
            if f.period_start and 80 <= (f.period_end - f.period_start).days <= 100
        }
    for cell in fy2025[1:3]:
        assert Decimal(cell["value"]) == reported[(cell["period_start"], cell["period_end"])]
    # Trailing twelve months at the latest column: the sum of the last four quarters.
    ttm = revenue["ttm"]
    last_four = [c for c in revenue["cells"] if c][-4:]
    assert ttm is not None and ttm["method"] == "quarter_sum"
    assert Decimal(ttm["value"]) == sum(Decimal(c["value"]) for c in last_four)
    eps = next(r for r in quarterly["rows"] if r["metric_id"] == "eps_diluted")
    assert eps["ttm"] is None  # EPS does not add up across quarters


def test_latest_values_carry_their_own_dates(client: TestClient) -> None:
    latest = {r["metric_id"]: r["cells"][0] for r in fundamentals(client, "META")["latest"]}
    cover = latest["shares_outstanding_cover"]
    assert cover["source_concept"].startswith("dei:EntityCommonStockSharesOutstanding")
    assert cover["period_end"] >= "2026-01-23" and cover["unit"] == "shares"


# ---------- filing reconciliation (ADR-021) ----------

AAPL_10K, AAPL_10Q = "0000320193-25-000079", "0000320193-26-000020"


def reconciliation(sessions: sessionmaker[Session], accession: str) -> FilingReconciliation:
    with sessions() as session:
        return session.scalars(
            select(FilingReconciliation).where(FilingReconciliation.accession_number == accession)
        ).one()


def test_apple_latest_10k_reconciles_with_zero_mismatches(
    replayed: list[IngestionRun], sessions: sessionmaker[Session]
) -> None:
    row = reconciliation(sessions, AAPL_10K)
    assert (row.status, row.mismatched, row.missing, row.extra, row.checks_failed) == (
        "pass",
        0,
        0,
        0,
        0,
    )
    assert row.checked == row.matched + row.restated_later
    assert row.checked > 30
    with sessions() as session:
        identities = session.scalars(
            select(ReconciliationItem).where(
                ReconciliationItem.reconciliation_id == row.id,
                ReconciliationItem.check_kind == "identity",
            )
        ).all()
    assert identities and {i.status for i in identities} == {"ok"}


def test_apple_latest_10q_quarters_match_the_reported_three_months(
    replayed: list[IngestionRun], sessions: sessionmaker[Session]
) -> None:
    row = reconciliation(sessions, AAPL_10Q)
    assert (row.status, row.mismatched, row.missing) == ("pass", 0, 0)
    with sessions() as session:
        quarters = session.scalars(
            select(ReconciliationItem).where(
                ReconciliationItem.reconciliation_id == row.id,
                ReconciliationItem.check_kind == "quarter",
            )
        ).all()
    assert quarters and {q.status for q in quarters} == {"ok"}


def test_a_value_that_differs_from_the_filing_is_caught(
    replayed: list[IngestionRun], sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filing's own XBRL with Apple's FY2025 revenue changed by $1: a mismatch."""
    monkeypatch.setattr(reconcile, "METHODOLOGY_VERSION", "test-injected")
    content = (FIXTURES / f"{AAPL_10K}_instance.xml").read_text(encoding="utf-8")
    changed = content.replace(">416161000000<", ">416161000001<", 1)
    assert changed != content
    with sessions() as session:
        filing = session.scalars(select(Filing).where(Filing.accession_number == AAPL_10K)).one()
        run_id = session.scalars(select(IngestionRun.id)).first()
        assert run_id is not None
        row = reconcile.reconcile_filing(
            session,
            entity_id=filing.entity_id,
            filing=filing,
            instance=parse_instance(changed.encode()),
            sums=[],
            source_url="https://www.sec.gov/Archives/edgar/data/320193/x_htm.xml",
            sha256="0" * 64,
            run_id=run_id,
            with_split_check=False,
        )
        assert row is not None and (row.status, row.mismatched) == ("fail", 1)
        item = session.scalars(
            select(ReconciliationItem).where(
                ReconciliationItem.reconciliation_id == row.id,
                ReconciliationItem.status == "mismatch",
            )
        ).one()
        assert (item.metric_id, item.filing_value, item.stored_value) == (
            "revenue",
            Decimal(416161000001),
            Decimal(416161000000),
        )
        session.rollback()


def test_reconciliation_api_lists_latest_filings_and_their_items(client: TestClient) -> None:
    listing = client.get("/reconciliation").json()
    by_filing = {(f["ticker"], f["form"]): f for f in listing["filings"]}
    assert by_filing[("AAPL", "10-K")]["accession"] == AAPL_10K
    assert by_filing[("AAPL", "10-Q")]["accession"] == AAPL_10Q
    assert {f["status"] for f in listing["filings"]} == {"pass"}
    assert client.get("/reconciliation", params={"status": "fail"}).json()["filings"] == []
    detail = client.get(f"/reconciliation/{AAPL_10K}").json()
    assert detail["filing"]["instance_url"].endswith("aapl-20250927_htm.xml")
    revenue = next(
        i
        for i in detail["items"]
        if i["metric_id"] == "revenue" and i["period_end"] == "2025-09-27"
    )
    assert (revenue["status"], revenue["filing_value"]) == ("match", "416161000000")
    assert client.get("/reconciliation/0000000000-00-000000").status_code == 404


# ---------- valuation (M1.2, ADR-022) ----------

VALUED_AT = "2026-10-06T12:00:00Z"  # the recorded closes end on 2026-10-05


def valuation(client: TestClient, ticker: str, known_at: str) -> dict[str, Any]:
    response = client.get(f"/instruments/{ticker}/valuation", params={"known_at": known_at})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_every_multiple_shows_its_inputs_dates_and_sources(client: TestClient) -> None:
    body = valuation(client, "AAPL", VALUED_AT)
    assert body["price"]["status"] == "ok" and body["price"]["day"] == "2026-10-05"
    assert body["price"]["source_url"].startswith("https://data.alpaca.markets/v2/stocks/bars")
    metrics = {m["metric_id"]: m for m in body["metrics"]}
    assert list(metrics) == [
        "market_cap",
        "enterprise_value",
        "pe_ratio_ttm",
        "ev_to_ebitda",
        "ev_to_sales",
        "price_to_book",
        "fcf_yield",
        "earnings_yield",
    ]
    for metric in metrics.values():
        assert metric["value"] is not None, metric
        assert metric["inputs"], metric["metric_id"]
        for given in metric["inputs"]:
            assert given["period_end"] is not None
            if given["name"] not in ("price", "market_cap", "enterprise_value"):
                assert given["sources"], (metric["metric_id"], given["name"])
                assert all(
                    s["filing"]["url"].startswith("https://www.sec.gov/") for s in given["sources"]
                )
    cap = Decimal(metrics["market_cap"]["value"])
    assert Decimal("2e12") < cap < Decimal("6e12")  # Apple: trillions, not a split-basis error
    assert Decimal(15) < Decimal(metrics["pe_ratio_ttm"]["value"]) < Decimal(80)
    eps = next(i for i in metrics["pe_ratio_ttm"]["inputs"] if i["name"] == "eps_diluted_ttm")
    assert len(eps["sources"]) in (1, 3)  # the fiscal year, or year + year-to-date pair


def test_a_past_date_uses_only_filings_and_closes_public_then(client: TestClient) -> None:
    at = "2026-04-15T00:00:00Z"
    body = valuation(client, "AAPL", at)
    assert body["price"]["day"] <= "2026-04-14"
    published = [
        s["filing"]["published_at"]
        for m in body["metrics"]
        for i in m["inputs"]
        for s in i["sources"]
    ]
    assert published and max(published) <= "2026-04-15T00:00:00Z"
    today = valuation(client, "AAPL", VALUED_AT)
    assert body["metrics"][0]["value"] != today["metrics"][0]["value"]


def test_meta_market_cap_counts_both_share_classes(client: TestClient) -> None:
    body = valuation(client, "META", VALUED_AT)
    cap = next(m for m in body["metrics"] if m["metric_id"] == "market_cap")
    shares = next(i for i in cap["inputs"] if i["name"].startswith("shares_outstanding"))
    assert Decimal(shares["value"]) > Decimal(2_400_000_000)  # Class A + Class B
    assert shares["sources"][0]["source_concept"].endswith("(sum of classes)")


def test_no_multiple_from_a_stale_close(client: TestClient) -> None:
    body = valuation(client, "AAPL", "2026-10-20T00:00:00Z")  # last recorded close 2026-10-05
    assert body["price"]["status"] == "stale"
    assert {m["value"] for m in body["metrics"]} == {None}
    assert {m["reason"] for m in body["metrics"]} == {"unavailable"}
    assert all("older than five days" in m["detail"] for m in body["metrics"])


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
        ("fundamentals-meta", "/instruments/META/fundamentals", {}),
        ("reconciliation", "/reconciliation", {}),
        ("reconciliation-aapl-10k", f"/reconciliation/{AAPL_10K}", {}),
        ("valuation-aapl", "/instruments/AAPL/valuation", {"known_at": VALUED_AT}),
        (
            "valuation-aapl-stale",
            "/instruments/AAPL/valuation",
            {"known_at": "2026-10-20T00:00:00Z"},
        ),
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
