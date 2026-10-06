"""SEC adapter without network or database: client behaviour, parsing and concept selection.

Real data comes from the recorded fixtures in tests/fixtures/sec (see manifest.json there).
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest

from autotrading.adapters.sec.client import MAX_ATTEMPTS, SecClient, SecConfigError, SecRequestError
from autotrading.adapters.sec.concepts import METRIC_MAPPINGS, split_concept
from autotrading.adapters.sec.parsing import (
    filing_index_url,
    load_companyfacts,
    parse_acceptance,
    parse_company,
    parse_filings,
    publication_time,
    select_values,
)
from autotrading.adapters.sec.tickers import parse_tickers
from autotrading.domain.metrics import SEC_XBRL_METRICS
from autotrading.domain.provenance import end_of_day
from autotrading.ingestion.job import idempotency_key
from autotrading.ingestion.schedule import refresh_window

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sec"
UA = "Test Runner test@example.com"


SUBMISSIONS = "https://data.sec.gov/submissions/CIK0000320193.json"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------- client ----------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_user_agent_fails_fast(value: str | None) -> None:
    with pytest.raises(SecConfigError, match="SEC_USER_AGENT is not set"):
        SecClient(value or "")


def test_user_agent_needs_an_email_and_is_not_echoed() -> None:
    with pytest.raises(SecConfigError) as error:
        SecClient("Jane Private Name")
    assert "Jane" not in str(error.value)


def client_with(
    responses: list[httpx.Response],
) -> tuple[SecClient, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    return (
        SecClient(UA, transport=httpx.MockTransport(handler), sleep=sleeps.append),
        requests,
        sleeps,
    )


def test_every_attempt_takes_a_token_and_sends_the_user_agent() -> None:
    client, requests, sleeps = client_with(
        [httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json={"ok": 1})]
    )
    tokens: list[None] = []
    payload = client.get(SUBMISSIONS, lambda: tokens.append(None))
    assert json.loads(payload.content) == {"ok": 1}
    assert payload.source_url == SUBMISSIONS
    assert len(tokens) == 2
    assert sleeps == [3.0]  # Retry-After honoured
    assert all(r.headers["User-Agent"] == UA for r in requests)


def test_throttling_that_never_ends_fails_the_request() -> None:
    client, requests, sleeps = client_with([httpx.Response(403)] * MAX_ATTEMPTS)
    with pytest.raises(SecRequestError, match="HTTP 403"):
        client.get(SUBMISSIONS, lambda: None)
    assert len(requests) == MAX_ATTEMPTS
    assert sleeps == [2.0, 4.0, 8.0]  # exponential backoff between attempts


@pytest.mark.parametrize(
    "url",
    [
        "https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2024.json",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        "http://data.sec.gov/submissions/CIK0000320193.json",
        "https://example.com/submissions/CIK0000320193.json",
    ],
)
def test_only_the_endpoints_the_adapter_uses_are_requested(url: str) -> None:
    client, _, _ = client_with([httpx.Response(200, content=b"{}")])
    with pytest.raises(SecRequestError, match="refused"):
        client.get(url, lambda: None)


def test_not_found_is_an_error_unless_allowed() -> None:
    client, _, _ = client_with([httpx.Response(404), httpx.Response(404)])
    assert client.get(SUBMISSIONS, lambda: None, allow_missing=True) is None
    with pytest.raises(SecRequestError, match="HTTP 404"):
        client.get(SUBMISSIONS, lambda: None)


# ---------- time rules (ADR-013) ----------


def test_acceptance_time_is_utc() -> None:
    # AAPL 8-K 0000320193-26-000018: EDGAR's index page shows 2026-07-30 16:30:28 (ET).
    accepted = parse_acceptance("2026-07-30T20:30:28.000Z")
    assert accepted == datetime(2026, 7, 30, 20, 30, 28, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [None, "", "2017-06-07T00:00:00.000Z", "2017-06-07T04:00:00.000Z"],  # 00:00 UTC, 00:00 NY
)
def test_missing_or_date_only_acceptance_falls_back_to_end_of_filing_day(
    value: str | None,
) -> None:
    accepted = parse_acceptance(value)
    assert accepted is None
    assert publication_time(accepted, date(2017, 6, 7)) == (end_of_day(date(2017, 6, 7)), "day")


def test_filing_links_point_at_the_edgar_index_page() -> None:
    assert filing_index_url("0000320193", "0001193125-10-012091") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000119312510012091/"
        "0001193125-10-012091-index.htm"
    )


# ---------- submissions (real fixture) ----------


def test_submissions_list_every_filing_with_its_acceptance_time() -> None:
    main = json.loads(fixture("submissions_CIK0000320193.json"))
    company = parse_company(main)
    assert (company.cik, company.tickers) == ("0000320193", ["AAPL"])
    assert company.extra_pages == ["CIK0000320193-submissions-001.json"]

    recent = parse_filings(main["filings"]["recent"], company.cik)
    older = parse_filings(json.loads(fixture(company.extra_pages[0])), company.cik)
    by_accession = {f.accession_number: f for f in recent + older}
    restated = by_accession["0001193125-10-012091"]
    assert (restated.form, restated.filing_date) == ("10-K/A", date(2010, 1, 25))
    assert restated.published() == (datetime(2010, 1, 25, 21, 25, 58, tzinfo=UTC), "exact")
    assert len(by_accession) == len(recent) + len(older)  # pages do not overlap


def test_ticker_file_maps_universe_tickers_to_ciks() -> None:
    listed = {row.ticker: row for row in parse_tickers(fixture("company_tickers_exchange.json"))}
    assert (listed["AAPL"].cik, listed["AAPL"].exchange) == ("0000320193", "Nasdaq")
    assert listed["JPM"].exchange == "NYSE"


# ---------- concept selection ----------


def obs(
    accn: str, val: Any, end: str, start: str | None = "2024-01-01", **extra: Any
) -> dict[str, Any]:
    row = {"accn": accn, "val": val, "end": end, "filed": "2025-02-01", "fy": 2024, "fp": "FY"}
    if start is not None:
        row["start"] = start
    return {**row, **extra}


def facts(concepts: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    return {"facts": {"us-gaap": {name: {"units": units} for name, units in concepts.items()}}}


def test_highest_priority_concept_wins_per_filing_and_period() -> None:
    values = select_values(
        facts(
            {
                "Revenues": {
                    "USD": [obs("A", 101, "2024-12-31"), obs("B", 205, "2025-12-31", "2025-01-01")]
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "USD": [obs("A", 100, "2024-12-31")]
                },
            }
        )
    )
    chosen = {(v.accession, v.period_end.year): (v.concept, v.value) for v in values}
    assert chosen == {
        ("A", 2024): ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", Decimal(100)),
        ("B", 2025): ("us-gaap:Revenues", Decimal(205)),  # filing B only reports Revenues
    }


def test_wrong_unit_wrong_period_type_and_repeats_are_dropped() -> None:
    values = select_values(
        facts(
            {
                "EarningsPerShareDiluted": {
                    "USD/shares": [obs("A", Decimal("7.46"), "2024-12-31")] * 2,
                    "pure": [obs("A", Decimal("7.46"), "2024-12-31")],
                },
                "CashAndCashEquivalentsAtCarryingValue": {
                    "USD": [obs("A", 5, "2024-12-31", start=None), obs("A", 6, "2024-12-31")]
                },
            }
        )
    )
    assert sorted((v.metric_id, v.unit, v.value, v.period_start) for v in values) == [
        ("cash", "USD", Decimal(5), None),
        ("eps_diluted", "USD/shares", Decimal("7.46"), date(2024, 1, 1)),
    ]


def test_concepts_are_read_across_taxonomies_in_priority_order() -> None:
    authorization = {"units": {"USD": [obs("A", 50, "2024-01-31", start=None)]}}
    older_tag = {"units": {"USD": [obs("A", 40, "2024-01-31", start=None)]}}
    cover = {"units": {"shares": [obs("A", 2190, "2025-10-17", start=None)]}}
    values = select_values(
        {
            "facts": {
                "srt": {"StockRepurchaseProgramAuthorizedAmount1": authorization},
                "us-gaap": {"StockRepurchaseProgramAuthorizedAmount1": older_tag},
                "dei": {"EntityCommonStockSharesOutstanding": cover},
            }
        }
    )
    assert sorted((v.metric_id, v.concept, v.value) for v in values) == [
        ("repurchase_authorized", "srt:StockRepurchaseProgramAuthorizedAmount1", Decimal(50)),
        ("shares_outstanding_cover", "dei:EntityCommonStockSharesOutstanding", Decimal(2190)),
    ]


@pytest.mark.parametrize("concept", ["Revenues", "ifrs-full:Revenue", "us-gaap:"])
def test_concepts_must_be_qualified_by_a_known_taxonomy(concept: str) -> None:
    with pytest.raises(ValueError, match="qualified"):
        split_concept(concept)


def test_two_values_for_one_filing_and_period_are_both_kept_for_the_conflict_check() -> None:
    values = select_values(
        facts({"NetIncomeLoss": {"USD": [obs("A", 1, "2024-12-31"), obs("A", 2, "2024-12-31")]}})
    )
    assert sorted(v.value for v in values) == [1, 2]


def test_real_company_facts_contain_the_apple_restatement() -> None:
    values = select_values(load_companyfacts(fixture("companyfacts_CIK0000320193.json")))
    fy2008 = {
        v.accession: v.value
        for v in values
        if v.metric_id == "net_income"
        and v.period_end == date(2008, 9, 27)
        and v.period_start == date(2007, 9, 30)
    }
    assert fy2008["0001193125-09-214859"] == Decimal("4834000000")
    assert fy2008["0001193125-10-012091"] == Decimal("6119000000")
    assert {v.metric_id for v in values} <= set(SEC_XBRL_METRICS)
    assert all(isinstance(v.value, Decimal) for v in values)


def test_every_mapped_metric_is_registered_with_the_glossary() -> None:
    assert [m.metric_id for m in METRIC_MAPPINGS] == list(SEC_XBRL_METRICS)


# ---------- refresh windows ----------


def test_scheduled_refresh_is_once_per_singapore_day_and_manual_always_runs() -> None:
    morning = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)  # 10:00 SGT
    evening = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)  # 22:00 SGT, same SGT day
    scheduled = refresh_window(morning, manual=False)
    assert scheduled.start == datetime(2026, 10, 4, 16, 0, tzinfo=UTC)  # 00:00 SGT
    assert scheduled.end == datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
    assert refresh_window(evening, manual=False) == scheduled

    def key(window: Any) -> str:
        return idempotency_key("sec_edgar", "sec.tickers", {"tickers": ["AAPL"]}, window)

    assert key(refresh_window(morning, manual=True)) != key(refresh_window(evening, manual=True))


def test_next_scheduled_refresh_is_the_next_singapore_time_slot() -> None:
    from autotrading.ingestion.schedule import SCHEDULES

    sec, fred = SCHEDULES["sec_edgar"], SCHEDULES["fred"]
    before = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)  # 09:00 SGT
    after = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)  # 11:00 SGT
    assert sec.next_after(before) == datetime(2026, 10, 5, 2, 0, tzinfo=UTC)
    assert fred.next_after(before) == datetime(2026, 10, 5, 2, 15, tzinfo=UTC)
    assert sec.next_after(after) == datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
