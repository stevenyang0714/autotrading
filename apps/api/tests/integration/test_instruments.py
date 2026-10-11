"""M0.5b acceptance: the instrument API on recorded real SEC data (tests/fixtures/sec).

Apple: annual values match the filing they link to; "as known on" before the January 2010
10-K/A returns the original FY2008 net income. XOM: the predecessor Exxon Mobil Corp supplies
history and is the issuer before the 2026-07-01 reorganization (ADR-014).
Uses its own migrated database, so the ticker map does not collide with test_sec.py.
"""

import json
import os
import time
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
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.fred.series import FredSeriesJob
from autotrading.adapters.sec import reconcile
from autotrading.adapters.sec.instance import parse_instance
from autotrading.adapters.sec.refresh import (
    company_ciks,
    filing_xbrl_candidates,
    universe_predecessors,
)
from autotrading.config_sync import load_macro_series, load_sources, sync_macro_series, sync_sources
from autotrading.db.models import (
    AuditLog,
    EntityRelationship,
    Filing,
    FilingReconciliation,
    FinancialFact,
    Identifier,
    IngestionRun,
    Instrument,
    ReconciliationItem,
    Source,
    ValuationAssumptionSet,
)
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.facts import FinancialFactRepository
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay
from tests.factories import financial_fact
from tests.integration.conftest import alembic_config
from tests.sec_replay import (
    FIXTURES,
    RECORDED_EIGHT_KS,
    RECORDED_INSTANCES,
    recorded_registry,
    replay,
)

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
    config = get_settings().resolved_config_dir()
    with Session(engine) as session:
        sync_sources(session, load_sources(config / "sources.yaml"))
        sync_macro_series(session, load_macro_series(config / "macro_series.yaml"))
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    with Session(engine) as session:
        for source_id in ("sec_edgar", "fred"):
            source = session.get_one(Source, source_id)
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
        alpaca_replay.register_recorded(
            fred_replay.register_recorded(recorded_registry()), fixture=False
        ),
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
    # The 10-year Treasury yield for the DCF discount rate (M1.3a).
    treasury = runner.create_run(
        FredSeriesJob.name,
        {"series_id": "DGS10", "observation_start": fred_replay.RECORDED_SERIES["DGS10"]},
        WINDOW,
    )
    runner.execute(treasury)
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
    # tickers, 4 companies (META included), splits, filing XBRL of Apple and Meta (ADR-021),
    # then per company with recorded 8-Ks (Apple, Exxon Mobil Corp, Meta) the 8-K run (M1.4a)
    # and the earnings-release run of its Item 2.02 8-Ks (M1.5)
    assert [(r.job, r.status) for r in replayed] == (
        [("sec.tickers", "succeeded")]
        + [("sec.company", "succeeded")] * 4
        + [("alpaca.splits", "succeeded")]
        + [("sec.filing_xbrl", "succeeded")] * 2
        + [("sec.eight_k", "succeeded"), ("sec.earnings_release", "succeeded")] * 3
    )
    read = [f["accession"] for r in replayed[6:8] for f in r.params["filings"]]
    assert sorted(read) == sorted(RECORDED_INSTANCES)

    def accessions(job: str) -> list[str]:
        return sorted(
            f["accession"] for r in replayed[8:] if r.job == job for f in r.params["filings"]
        )

    assert accessions("sec.eight_k") == sorted(RECORDED_EIGHT_KS)
    debt_notice = "0001140361-25-018400"  # Item 8.01: not an earnings release
    assert accessions("sec.earnings_release") == sorted(RECORDED_EIGHT_KS - {debt_notice})
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


# ---------- fair value (M1.3a, ADR-023) ----------

DEFAULT_PARAMETERS = {
    "equity_risk_premium": "5",
    "terminal_growth": "2.5",
    "growth_bear": "0",
    "growth_base": "5",
    "growth_bull": "10",
    "subtract_sbc": True,
}


def fair_value(
    client: TestClient, ticker: str, known_at: str, assumptions: str | None = None
) -> dict[str, Any]:
    params = {"known_at": known_at} | ({"assumptions": assumptions} if assumptions else {})
    response = client.get(f"/instruments/{ticker}/fair-value", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_fair_value_names_method_assumptions_range_price_and_dates(client: TestClient) -> None:
    body = fair_value(client, "AAPL", VALUED_AT)
    assert body["label"] == "Model output, not fact"
    assert body["method"].startswith("Enterprise DCF of owner free cash flow")
    assert body["known_at"] == "2026-10-06T12:00:00Z"  # the model date
    assumptions = body["assumptions"]
    assert assumptions["version"] is None and "not reviewed" in assumptions["reason"]
    assert assumptions["parameters"] == DEFAULT_PARAMETERS

    dcf = body["dcf"]
    assert dcf["status"] == "ok", dcf["detail"]
    rate = dcf["discount_rate"]
    treasury = rate["risk_free"]
    assert treasury["series_id"] == "DGS10" and treasury["observation_date"] <= "2026-10-05"
    assert treasury["published_at"] <= "2026-10-06T12:00:00Z"
    assert Decimal(rate["value"]) == Decimal(treasury["value"]) + 5
    names = [i["name"] for i in dcf["inputs"]]
    assert names == ["owner_fcf", "net_debt", "shares_outstanding_cover"]
    owner = dcf["inputs"][0]
    assert {s["metric_id"] for s in owner["sources"]} == {
        "operating_cash_flow",
        "capex",
        "stock_based_compensation",
    }
    assert all(
        s["filing"]["url"].startswith("https://www.sec.gov/")
        for i in dcf["inputs"]
        for s in i["sources"]
    )
    scenarios = dcf["scenarios"]
    assert [s["scenario"] for s in scenarios] == ["bear", "base", "bull"]
    bear, base, bull = (Decimal(s["per_share"]) for s in scenarios)
    assert Decimal(0) < bear < base < bull

    comparison = body["comparison"]
    price = Decimal(comparison["price"]["close"])
    assert comparison["price"]["day"] == "2026-10-05" and comparison["detail"] is None
    assert Decimal(comparison["implied_upside"]) == ((base / price - 1) * 100).quantize(
        Decimal("0.01")
    )
    assert Decimal(comparison["margin_of_safety"]) == ((base - price) / base * 100).quantize(
        Decimal("0.01")
    )
    assert body["reverse_dcf"]["growth"] is not None

    relative = {r["metric_id"]: r for r in body["relative"]}
    assert list(relative) == [
        "pe_ratio_ttm",
        "ev_to_ebitda",
        "ev_to_sales",
        "price_to_book",
        "fcf_yield",
        "earnings_yield",
    ]
    shown = valuation(client, "AAPL", VALUED_AT)["metrics"]
    multiples = {m["metric_id"]: m["value"] for m in shown}
    pe = relative["pe_ratio_ttm"]
    assert pe["current"] == multiples["pe_ratio_ttm"]  # as on the Valuation block
    # One year of recorded closes: a dozen month ends, each valued as known then.
    assert 10 <= pe["observations"] <= 13 and pe["since"] >= "2025-09-30"
    assert pe["median"] is not None and 0 <= Decimal(pe["percentile"]) <= 100

    as_of = body["data_as_of"]
    assert as_of["latest_filing"]["form"] in ("10-Q", "10-K")
    assert as_of["latest_filing"]["published_at"] <= "2026-10-06T12:00:00Z"
    assert (as_of["price_day"], as_of["risk_free_date"]) == (
        "2026-10-05",
        treasury["observation_date"],
    )


def test_no_price_comparison_from_a_stale_close_but_the_dcf_stands(client: TestClient) -> None:
    body = fair_value(client, "AAPL", "2026-10-20T00:00:00Z")
    assert body["dcf"]["status"] == "ok" and len(body["dcf"]["scenarios"]) == 3
    comparison = body["comparison"]
    assert comparison["price"]["status"] == "stale"
    assert (comparison["implied_upside"], comparison["margin_of_safety"]) == (None, None)
    assert comparison["detail"].startswith("no valuation price")
    assert body["reverse_dcf"] == {"growth": None, "detail": "no valuation price"}


def restate_latest_operating_cash_flow(sessions: sessionmaker[Session], ticker: str) -> Decimal:
    """A new version of the latest year-to-date operating cash flow, public only in 2030."""
    with sessions() as session:
        fact = fair_value_fact(session, ticker)
        changed = fact.value + 1_000_000_000
        FinancialFactRepository(session).insert(
            financial_fact(
                entity_id=fact.entity_id,
                metric_id=fact.metric_id,
                value=str(changed),
                unit=fact.unit,
                fiscal_period=fact.fiscal_period,
                period_start=fact.period_start,
                period_end=fact.period_end,
                accession_id="0000000000-30-000001",
                provenance_overrides={
                    "source_id": "sec_edgar",
                    "published_at": datetime(2030, 1, 2, tzinfo=UTC),
                },
            ),
            actor="test:restatement",
        )
        session.commit()
    return changed


def fair_value_fact(session: Session, ticker: str) -> FinancialFact:
    instrument = client_instrument(session, ticker)
    assert instrument.entity_id is not None
    return session.scalars(
        select(FinancialFact)
        .where(
            FinancialFact.entity_id == instrument.entity_id,
            FinancialFact.metric_id == "operating_cash_flow",
            FinancialFact.period_start.is_not(None),
            FinancialFact.superseded_at.is_(None),
        )
        .order_by(FinancialFact.period_end.desc(), FinancialFact.published_at.desc())
        .limit(1)
    ).one()


def client_instrument(session: Session, ticker: str) -> Instrument:
    return session.scalars(
        select(Instrument)
        .join(Identifier, Identifier.instrument_id == Instrument.id)
        .where(Identifier.id_type == "ticker", Identifier.id_value == ticker)
    ).first() or pytest.fail(f"no {ticker}")


def save(client: TestClient, ticker: str, reason: str, **changes: object) -> dict[str, Any]:
    response = client.post(
        f"/instruments/{ticker}/assumptions",
        json={"parameters": DEFAULT_PARAMETERS | changes, "reason": reason},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_saved_version_reproduces_after_new_facts_and_versions(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    # META, so the AAPL web fixtures never see these versions or the 2030 restatement.
    listed = client.get("/instruments/META/assumptions").json()
    assert listed["versions"] == [] and listed["default"]["parameters"] == DEFAULT_PARAMETERS
    assert listed["limits"]["equity_risk_premium"] == {"minimum": "2", "maximum": "10"}
    default_at_t = fair_value(client, "META", VALUED_AT, "default")

    v1 = save(client, "meta", "Ads growth above default", growth_base="7")
    assert (v1["version"], v1["author"], v1["parameters"]["growth_base"]) == (1, "web", "7")
    with_v1 = fair_value(client, "META", VALUED_AT, "1")
    assert with_v1["assumptions"]["version"] == 1
    base = {s["scenario"]: s["per_share"] for s in with_v1["dcf"]["scenarios"]}["base"]
    assert Decimal(base) > Decimal(default_at_t["dcf"]["scenarios"][1]["per_share"])

    # Later: a restated cash flow (public in 2030) and a second version.
    restate_latest_operating_cash_flow(sessions, "META")
    v2 = save(client, "META", "Capex cycle peaks", growth_base="8", subtract_sbc=False)
    assert v2["version"] == 2

    # The same version at the same time gives exactly the same result (acceptance 2, 3).
    assert fair_value(client, "META", VALUED_AT, "1") == with_v1
    assert fair_value(client, "META", VALUED_AT, "default") == default_at_t
    # Without a version: the latest saved by then. Both were saved after T.
    assert fair_value(client, "META", VALUED_AT) == default_at_t
    later = fair_value(client, "META", "2030-06-01T00:00:00Z")
    assert later["assumptions"]["version"] == 2
    owner = {i["name"]: Decimal(i["value"]) for i in later["dcf"]["inputs"]}["owner_fcf"]
    before = {i["name"]: Decimal(i["value"]) for i in with_v1["dcf"]["inputs"]}["owner_fcf"]
    assert owner != before  # the restatement, and SBC left in
    assert (
        client.get(
            "/instruments/META/fair-value", params={"known_at": VALUED_AT, "assumptions": "9"}
        ).status_code
        == 404
    )

    listed = client.get("/instruments/META/assumptions").json()
    assert [v["version"] for v in listed["versions"]] == [2, 1]
    assert listed["versions"][1]["reason"] == "Ads growth above default"

    # Audited, and never changed in place.
    audit = client.get("/audit-log", params={"table": "valuation_assumptions"}).json()
    assert [(e["action"], e["actor"], e["object_label"]) for e in audit["entries"]] == [
        ("insert", "web", "META assumptions v2"),
        ("insert", "web", "META assumptions v1"),
    ]
    with sessions() as session, pytest.raises(DBAPIError, match="not allowed"):
        session.execute(
            update(ValuationAssumptionSet)
            .where(ValuationAssumptionSet.version == 1)
            .values(reason="rewritten")
        )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            {"parameters": DEFAULT_PARAMETERS | {"growth_bear": "12"}, "reason": "x"},
            "bear <= base <= bull",
        ),
        (
            {"parameters": DEFAULT_PARAMETERS | {"equity_risk_premium": "15"}, "reason": "x"},
            "less than or equal to 10",
        ),
        ({"parameters": DEFAULT_PARAMETERS, "reason": "   "}, "at least 1 character"),
        ({"parameters": DEFAULT_PARAMETERS | {"beta": "1.1"}, "reason": "x"}, "Extra inputs"),
    ],
)
def test_invalid_assumptions_are_refused_with_the_reason(
    client: TestClient, body: dict[str, Any], message: str
) -> None:
    before = client.get("/instruments/XOM/assumptions").json()["versions"]
    response = client.post("/instruments/XOM/assumptions", json=body)
    assert response.status_code == 422 and message in response.text
    assert client.get("/instruments/XOM/assumptions").json()["versions"] == before


def test_fair_value_for_unknown_tickers_and_versions(client: TestClient) -> None:
    assert client.get("/instruments/NOPE/fair-value").status_code == 404
    assert (
        client.post(
            "/instruments/NOPE/assumptions", json={"parameters": DEFAULT_PARAMETERS, "reason": "x"}
        ).status_code
        == 404
    )
    assert (
        client.get("/instruments/AAPL/fair-value", params={"assumptions": "latest"}).status_code
        == 422
    )


# ---------- research record (M1.3b, ADR-024) ----------

AAPL_10K = "0000320193-25-000079"


def research(client: TestClient, ticker: str, known_at: str) -> dict[str, Any]:
    response = client.get(f"/instruments/{ticker}/research", params={"known_at": known_at})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def cells(body: dict[str, Any], end: str) -> dict[str, dict[str, Any]]:
    index = [p["period_end"] for p in body["periods"]].index(end)
    return {row["metric_id"]: row["cells"][index] for row in body["rows"]}


def test_research_record_recomputes_from_the_reported_facts(client: TestClient) -> None:
    body = research(client, "AAPL", VALUED_AT)
    periods = [(p["kind"], p["period_start"], p["period_end"]) for p in body["periods"]]
    assert periods[:3] == [
        ("ttm", "2025-06-29", "2026-06-27"),
        ("fiscal_year", "2024-09-29", "2025-09-27"),
        ("fiscal_year", "2023-10-01", "2024-09-28"),
    ]
    assert len(periods) == 6  # TTM and five fiscal years
    assert {row["section"] for row in body["rows"]} == {
        "economics",
        "quality",
        "capital_allocation",
    }
    fy = cells(body, "2025-09-27")
    gross = fy["gross_margin"]
    parts = {i["name"]: Decimal(i["value"]) for i in gross["inputs"]}
    assert Decimal(gross["value"]) == (parts["gross_profit"] / parts["revenue"] * 100).quantize(
        Decimal("0.01")
    )
    assert {s["filing"]["accession"] for i in gross["inputs"] for s in i["sources"]} == {AAPL_10K}
    expected = {
        "gross_margin": "46.91",
        "roic": "83.14",
        "roe": "171.42",
        "fcf_conversion": "88.18",
        "net_debt_to_ebitda": "0.43",
        "cash_returned": "106132000000",
        "cash_returned_to_fcf": "107.46",
        "diluted_shares_change": "-2.62",
    }
    assert {m: fy[m]["value"] for m in expected} == expected
    nopat, opening, closing = fy["roic"]["inputs"]
    assert (nopat["name"], opening["period_end"], closing["period_end"]) == (
        "nopat",
        "2024-09-28",
        "2025-09-27",
    )


def test_research_record_names_what_is_missing(client: TestClient) -> None:
    xom = cells(research(client, "XOM", VALUED_AT), "2025-12-31")
    assert xom["roic"]["detail"] == "not reported: operating income"
    assert xom["stock_based_compensation"]["detail"] == "not reported: stock-based compensation"
    assert xom["net_margin"]["value"] is not None  # the rest still stands
    # No diluted share count after 2013, but diluted EPS equals basic EPS (ADR-025 B11).
    change = xom["diluted_shares_change"]
    assert change["value"] == "0.16"  # 4,305M / 4,298M basic shares - 1
    now = change["inputs"][0]
    assert now["note"] == "basic weighted shares: diluted EPS equals basic EPS for the period"
    assert [s["metric_id"] for s in now["sources"]] == ["basic_shares", "eps_diluted", "eps_basic"]
    meta = cells(research(client, "META", VALUED_AT), "2025-12-31")
    assert meta["gross_margin"]["detail"] == "not reported: gross profit"


def test_research_record_on_a_past_date_uses_only_filings_public_then(
    client: TestClient,
) -> None:
    body = research(client, "AAPL", "2026-04-15T00:00:00Z")
    assert body["periods"][0]["period_end"] == "2025-12-27"  # Q1 FY2026 10-Q, late January
    published = [
        s["filing"]["published_at"]
        for row in body["rows"]
        for cell in row["cells"]
        for i in cell["inputs"]
        for s in i["sources"]
    ]
    assert published and max(published) <= "2026-04-15T00:00:00Z"


def test_research_dashboard_matches_valuation_and_fair_value(client: TestClient) -> None:
    started = time.monotonic()
    response = client.get("/research", params={"known_at": VALUED_AT})
    elapsed = time.monotonic() - started
    assert response.status_code == 200, response.text
    body = response.json()
    assert elapsed < 3, elapsed
    assert body["label"] == "Model output, not fact"
    rows = {r["ticker"]: r for r in body["rows"]}
    assert list(rows) == ["AAPL", "META", "XOM"]
    apple = rows["AAPL"]
    values = {v["metric_id"]: v for v in apple["values"]}
    assert apple["period"]["period_end"] == "2026-06-27"
    record = cells(research(client, "AAPL", VALUED_AT), "2026-06-27")
    assert values["roic"]["value"] == record["roic"]["value"]
    shown = valuation(client, "AAPL", VALUED_AT)["metrics"]
    multiples = {m["metric_id"]: m["value"] for m in shown}
    assert values["pe_ratio_ttm"]["value"] == multiples["pe_ratio_ttm"]
    fair = fair_value(client, "AAPL", VALUED_AT)
    base = next(s for s in fair["dcf"]["scenarios"] if s["scenario"] == "base")
    assert apple["fair_value"]["base_per_share"] == base["per_share"]
    assert apple["fair_value"]["implied_upside"] == fair["comparison"]["implied_upside"]
    assert apple["fair_value"]["assumptions_version"] == fair["assumptions"]["version"]
    assert rows["XOM"]["fair_value"]["status"] == "unavailable"  # no SBC line
    stale = client.get("/research", params={"known_at": "2026-10-20T00:00:00Z"}).json()
    apple_stale = next(r for r in stale["rows"] if r["ticker"] == "AAPL")
    assert apple_stale["price"]["status"] == "stale"
    assert apple_stale["fair_value"]["implied_upside"] is None
    assert apple_stale["fair_value"]["comparison_detail"].startswith("no valuation price")


# ---------- buybacks (M1.4a, ADR-025) ----------


def buybacks(client: TestClient, ticker: str, known_at: str) -> dict[str, Any]:
    response = client.get(f"/instruments/{ticker}/buybacks", params={"known_at": known_at})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def by_period(body: dict[str, Any], end: str) -> dict[str, dict[str, Any]]:
    index = [p["period_end"] for p in body["periods"]].index(end)
    return {row["metric_id"]: row["cells"][index] for row in body["rows"]}


def test_authorization_repurchase_and_net_reduction_are_shown_apart(client: TestClient) -> None:
    body = buybacks(client, "AAPL", VALUED_AT)
    # Authorization: the 8-Ks' own sentences, at their acceptance times.
    events = [(e["day"], e["kind"], e["amount"]) for e in body["announcements"]]
    assert events == [
        ("2026-04-30", "increase", "100000000000"),
        ("2024-05-02", "increase", "110000000000"),
    ]
    latest = body["announcements"][0]
    assert {s["accession"] for s in latest["sources"]} == {"0000320193-26-000011"}
    assert all(s["published_at"] == latest["first_published_at"] for s in latest["sources"])
    assert all(
        len(s["sentence"]) <= 300 and s["url"].startswith("https://www.sec.gov/")
        for s in latest["sources"]
    )
    tagged = body["tagged_authorized"]
    assert (tagged["value"], tagged["period_end"]) == ("315000000000", "2021-12-25")
    # Actual repurchase and net share reduction, each with its inputs.
    fy = by_period(body, "2025-09-27")
    assert (fy["share_repurchases"]["value"], fy["net_share_reduction"]["value"]) == (
        "90711000000",
        "343526000",
    )
    assert fy["debt_funded_buyback"]["value"] == "0"
    # Intensity needs a close at the period end: the recorded closes start in October 2025.
    ttm = by_period(body, "2026-06-27")
    cap = next(i for i in ttm["buyback_intensity"]["inputs"] if i["name"] == "market_cap")
    assert Decimal(ttm["buyback_intensity"]["value"]) > 0 and cap["period_end"] == "2026-06-27"
    assert fy["buyback_intensity"]["detail"] == "not reported: end-of-day close by 2025-09-27"


def test_every_recorded_company_has_the_three_parts(client: TestClient) -> None:
    for ticker in ("AAPL", "META", "XOM"):
        body = buybacks(client, ticker, VALUED_AT)
        assert isinstance(body["announcements"], list), ticker
        metrics = {row["metric_id"] for row in body["rows"]}
        assert {"share_repurchases", "net_share_reduction"} <= metrics, ticker
    meta = buybacks(client, "META", VALUED_AT)["announcements"]
    assert ("2024-02-01", "increase", "50000000000") in [
        (e["day"], e["kind"], e["amount"]) for e in meta
    ]
    assert any(e["kind"] == "remaining" and e["amount"] == "30930000000" for e in meta)
    xom = buybacks(client, "XOM", VALUED_AT)["announcements"]
    assert [(e["kind"], e["amount"]) for e in xom] == [("plan", "20000000000")]


def test_buybacks_on_a_past_date_use_only_8ks_public_then(client: TestClient) -> None:
    body = buybacks(client, "AAPL", "2026-04-15T00:00:00Z")
    assert [e["day"] for e in body["announcements"]] == ["2024-05-02"]
    assert body["periods"][0]["period_end"] == "2025-12-27"


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
    # One saved AAPL version for the version picker (the write tests above use META and XOM).
    if not client.get("/instruments/AAPL/assumptions").json()["versions"]:
        save(client, "AAPL", "Illustrative: services mix supports faster growth", growth_base="7")
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
        (
            "fair-value-aapl",
            "/instruments/AAPL/fair-value",
            {"known_at": VALUED_AT, "assumptions": "default"},
        ),
        (
            "fair-value-aapl-v1",
            "/instruments/AAPL/fair-value",
            {"known_at": VALUED_AT, "assumptions": "1"},
        ),
        (
            "fair-value-aapl-stale",
            "/instruments/AAPL/fair-value",
            {"known_at": "2026-10-20T00:00:00Z", "assumptions": "default"},
        ),
        (
            "fair-value-xom",
            "/instruments/XOM/fair-value",
            {"known_at": VALUED_AT, "assumptions": "default"},
        ),
        ("assumptions-aapl", "/instruments/AAPL/assumptions", {}),
        ("research-aapl", "/instruments/AAPL/research", {"known_at": VALUED_AT}),
        ("research-xom", "/instruments/XOM/research", {"known_at": VALUED_AT}),
        ("research-dashboard", "/research", {"known_at": VALUED_AT}),
        ("research-dashboard-stale", "/research", {"known_at": "2026-10-20T00:00:00Z"}),
        # buybacks-*: recorded with their states by test_buyback_states.py (M1.4b)
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
