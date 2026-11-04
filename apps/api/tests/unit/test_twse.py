"""The TWSE OpenAPI files (M3.7, ADR-039): parsers on the recorded files, the market-cap
ranking behind config/universe_tw.yaml, the margin chain, the reference price check and the
client's allowed paths. M3.11 (ADR-042 SC1, SC2): the listed companies, their industry names
and when the company file is fetched."""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2 as httpx
import pytest
import yaml

from autotrading.adapters.twse.client import (
    ALLOWED_PATHS,
    DAY,
    TwseClient,
    TwseRequestError,
    public_url,
)
from autotrading.adapters.twse.daily import COMPANY_CODE
from autotrading.adapters.twse.refresh import weekly_companies
from autotrading.config_sync import load_sources
from autotrading.domain.market_calendar import load_calendar
from autotrading.domain.twse import (
    MarginRow,
    TwseFormatError,
    closures,
    company_rows,
    day_rows,
    ex_right_rows,
    gregorian_date,
    holiday_rows,
    margin_dating,
    margin_rows,
    number,
    rank_market_cap,
    reference_gap,
    roc_date,
    session_of,
    tick,
    valuation_rows,
)
from autotrading.ingestion.schedule import SCHEDULES, TWSE
from autotrading.repositories.listed import industry_names
from autotrading.settings import get_settings
from tests.twse_replay import FIXTURES, payload

CONFIG = Path(get_settings().resolved_config_dir())


def test_dates_and_numbers() -> None:
    assert roc_date("1151021") == roc_date("115/10/21") == date(2026, 10, 21)
    assert roc_date("991231") == date(2010, 12, 31)  # a two-digit ROC year
    assert gregorian_date("20261021") == date(2026, 10, 21)
    assert number("1,236") == Decimal(1236)
    assert number("-0.0400") == Decimal("-0.0400")
    assert number("") is number("--") is number(" - ") is None
    with pytest.raises(TwseFormatError):
        number("X0.50")
    with pytest.raises(TwseFormatError):
        roc_date("2026-10-21")


def test_the_recorded_day_files_parse() -> None:
    days = {r.code: r for r in day_rows(payload("d1", "STOCK_DAY_ALL"))}
    assert session_of(list(days.values())) == date(2026, 10, 21)
    tsmc = days["2330"]
    assert (tsmc.close, tsmc.change, tsmc.volume) == (
        Decimal("2420.00"),
        Decimal("15.0000"),
        Decimal(27095005),
    )
    assert days["0050"].close == Decimal("108.15")

    valuation = {r.code: r for r in valuation_rows(payload("d1", "BWIBBU_d"))}
    assert valuation["2330"].session == date(2026, 10, 21)
    assert (valuation["2330"].pe, valuation["2330"].pb) == (Decimal("28.05"), Decimal("9.76"))
    assert valuation["2330"].dividend_year == 2025  # ROC 114
    assert valuation["2330"].fiscal_quarter == "2026Q2"

    margin = {r.code: r for r in margin_rows(payload("d1", "MI_MARGN"))}
    assert margin["2330"].values["margin_balance"] == Decimal(35330)
    assert margin["2330"].values["margin_balance_previous"] == Decimal(34401)
    assert margin["2330"].values["short_sale"] == Decimal(0)  # a blank cell is zero
    # the margin limit is 25% of the issued shares in lots of 1,000: the unit is lots (TW6)
    companies = {c.code: c for c in company_rows(payload("d1", "t187ap03_L"))}
    shares = companies["2330"].shares
    assert shares is not None
    assert margin["2330"].values["margin_limit"] == (shares / 1000 / 4).to_integral_value(
        rounding="ROUND_DOWN"
    )

    ex = {(r.code, r.ex_date): r for r in ex_right_rows(payload("d1", "TWT48U_ALL"))}
    assert ex[("0056", date(2026, 10, 22))].cash == Decimal("1.72")
    assert ex[("00400A", date(2026, 11, 6))].cash is None  # announced, amount not yet known


def test_a_changed_file_fails_instead_of_storing_half() -> None:
    rows = payload("d1", "STOCK_DAY_ALL")
    del rows[0]["ClosingPrice"]
    with pytest.raises(TwseFormatError, match="ClosingPrice"):
        day_rows(rows)
    mixed = payload("d1", "STOCK_DAY_ALL")
    mixed[0]["Date"] = "1151020"
    with pytest.raises(TwseFormatError, match="2 sessions"):
        session_of(day_rows(mixed))


def test_the_frozen_universe_is_the_recorded_top_ten_by_market_cap() -> None:
    universe = yaml.safe_load((CONFIG / "universe_tw.yaml").read_text())
    ranked = rank_market_cap(
        day_rows(payload("d1", "STOCK_DAY_ALL")), company_rows(payload("d1", "t187ap03_L"))
    )
    assert [r.code for r in ranked[:10]] == universe["equities"]
    assert "0050" not in {r.code for r in ranked}  # an ETF has no company row
    # the ranking cites the exact recorded files
    for name, sha in universe["ranking"]["inputs"].items():
        assert hashlib.sha256((FIXTURES / f"d1_{name}.json").read_bytes()).hexdigest() == sha


def test_every_listed_company_has_its_listing_date_and_a_named_industry() -> None:
    companies = {c.code: c for c in company_rows(payload("d1", "t187ap03_L"))}
    assert len(companies) == 1097
    assert companies["2603"].listed_on == date(1987, 9, 21)
    assert all(c.listed_on is not None for c in companies.values())
    names = industry_names(CONFIG)
    assert {c.industry for c in companies.values()} <= set(names)
    assert names["24"] == "半導體業" and names["91"] == "存託憑證"
    # 91 are depositary receipts: ten of them, some with six-character codes
    receipts = sorted(code for code, c in companies.items() if c.industry == "91")
    assert len(receipts) == 10 and "910322" in receipts


def test_a_four_digit_code_of_the_day_file_is_always_a_company() -> None:
    """The rule behind fetching the company file again (ADR-042 SC2): a four-digit code the file
    was never seen with is a new listing, never a fund or a warrant."""
    companies = {c.code for c in company_rows(payload("d1", "t187ap03_L"))}
    for day in ("d1", "d2"):
        codes = {r.code for r in day_rows(payload(day, "STOCK_DAY_ALL"))}
        four = {code for code in codes if COMPANY_CODE.fullmatch(code)}
        assert four and four <= companies
        assert "0050" not in four and "0056" not in four


def test_the_company_file_is_fetched_weekly_on_the_first_taipei_slot_of_monday() -> None:
    taipei = ZoneInfo("Asia/Taipei")
    monday = datetime(2026, 11, 2, 7, 40, tzinfo=taipei)
    assert weekly_companies("07:40", monday)
    assert not weekly_companies("09:40", monday)
    assert not weekly_companies("07:40", datetime(2026, 11, 3, 7, 40, tzinfo=taipei))


def test_the_xtai_calendar_matches_the_recorded_holiday_schedule() -> None:
    calendar = load_calendar(yaml.safe_load((CONFIG / "market_calendar_xtai.yaml").read_text()))
    published = closures(holiday_rows(payload("d1", "holidaySchedule")))
    assert {d for d in calendar.holidays if d.year == 2026} == published
    # the 開始交易日 / 最後交易日 lines are sessions
    for day in (date(2026, 1, 2), date(2026, 2, 11), date(2026, 2, 23)):
        assert calendar.session(day) is not None


def _margin(code: str, before: int, today: int, short_before: int = 5, short: int = 5) -> MarginRow:
    values = {
        "margin_balance_previous": Decimal(before),
        "margin_balance": Decimal(today),
        "short_balance_previous": Decimal(short_before),
        "short_balance": Decimal(short),
    }
    return MarginRow(code, values, None)


def test_the_margin_file_is_dated_by_the_chain_of_balances() -> None:
    stored = {
        "2330": {"margin_balance": Decimal(100), "short_balance": Decimal(5)},
        "2454": {"margin_balance": Decimal(200), "short_balance": Decimal(5)},
    }
    moved = [_margin("2330", 100, 110), _margin("2454", 200, 190)]
    assert margin_dating(moved, None, adjacent=False).status == "unverified"
    assert margin_dating(moved, stored, adjacent=True).status == "verified"
    # still the stored session's file: every balance equals the stored one
    same = [_margin("2330", 90, 100), _margin("2454", 210, 200)]
    assert margin_dating(same, stored, adjacent=True).status == "not_updated"
    # a session lost in between: the chain cannot link, the file is accepted unverified
    assert margin_dating(moved, stored, adjacent=False).status == "unverified"
    one_off = [_margin("2330", 100, 110), _margin("2454", 205, 190)]
    found = margin_dating(one_off, stored, adjacent=True)
    assert (found.status, found.mismatched) == ("partial", ("2454",))
    none = [_margin("2330", 101, 110), _margin("2454", 201, 190)]
    assert not margin_dating(none, stored, adjacent=True).accepted


def test_ticks_and_the_reference_price_check() -> None:
    assert tick(Decimal("9.99"), etf=False) == Decimal("0.01")
    assert tick(Decimal(2420), etf=False) == Decimal(5)
    assert tick(Decimal("108.15"), etf=True) == Decimal("0.05")
    day = date(2026, 10, 22)
    before = date(2026, 10, 21)
    # no action: the reference is the previous close
    assert (
        reference_gap("2330", day, Decimal(2440), Decimal(20), before, Decimal(2420), etf=False)
        is None
    )
    # a cash dividend of 20: the reference is 2400, the previous close less the dividend
    assert (
        reference_gap(
            "2330",
            day,
            Decimal(2410),
            Decimal(10),
            before,
            Decimal(2420),
            etf=False,
            cash=Decimal(20),
        )
        is None
    )
    # the same day without the dividend recorded: a gap of 20, four ticks of 5
    gap = reference_gap("2330", day, Decimal(2410), Decimal(10), before, Decimal(2420), etf=False)
    assert gap is not None and gap.reference == Decimal(2400) and "not yet recorded" in gap.note()
    # within one tick (5 at 2420): TWSE rounds the reference price to its tick
    assert (
        reference_gap("2330", day, Decimal(2430), Decimal(15), before, Decimal(2420), etf=False)
        is None
    )
    # the recorded ex-date of 0056 (2026-10-22, cash 1.72): TWSE states a change of 0, not the
    # change against the reference 57.03; with the dividend recorded there is nothing to check,
    # without it a change of 0 and another close is an action the file did not tell
    rows = {r.code: r for r in day_rows(payload("d2", "STOCK_DAY_ALL"))}
    fund = rows["0056"]
    assert fund.close == Decimal("56.30") and fund.change == 0
    assert fund.close is not None and fund.change is not None
    told = {r.code: r for r in ex_right_rows(payload("d1", "TWT48U_ALL")) if r.ex_date == day}
    assert told["0056"].cash == Decimal("1.72")
    assert (
        reference_gap(
            "0056",
            day,
            fund.close,
            fund.change,
            before,
            Decimal("58.75"),
            etf=True,
            cash=Decimal("1.72"),
        )
        is None
    )
    untold = reference_gap("0056", day, fund.close, fund.change, before, Decimal("58.75"), etf=True)
    assert untold is not None and untold.reference == Decimal("56.30")
    # a 10% stock dividend: 100 / 1.1 = 90.91
    assert (
        reference_gap(
            "2882",
            day,
            Decimal("91.0"),
            Decimal("0.1"),
            before,
            Decimal(100),
            etf=False,
            stock_ratio=Decimal("0.1"),
        )
        is None
    )


def test_the_client_reaches_only_the_six_licensed_files() -> None:
    assert len(ALLOWED_PATHS) == 6
    assert public_url(DAY) == "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    for refused in ("/rwd/zh/fund/T86", "/fund/MI_QFIIS_sort_20", "/exchangeReport/STOCK_DAY"):
        with pytest.raises(ValueError, match="not one of the licensed"):
            public_url(refused)


def test_the_client_retries_a_busy_server_and_refuses_non_json() -> None:
    calls: list[str] = []

    def busy_then_ok(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

    acquired: list[int] = []
    with TwseClient(transport=httpx.MockTransport(busy_then_ok), sleep=lambda _: None) as client:
        found = client.get(DAY, lambda: acquired.append(1))
    assert found.content == b"[]" and len(calls) == 2 and len(acquired) == 2
    assert found.source_url == public_url(DAY)

    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>blocked</html>")

    with (
        TwseClient(transport=httpx.MockTransport(html), sleep=lambda _: None) as client,
        pytest.raises(TwseRequestError, match="did not return JSON"),
    ):
        client.get(DAY, lambda: None)


def test_the_source_is_registered_as_licensed_open_data_at_one_request_every_3_seconds() -> None:
    sources = {s.id: s for s in load_sources(CONFIG / "sources.yaml").sources}
    twse = sources["twse_openapi"]
    assert (twse.tier, twse.license_status, twse.enabled) == (1, "public", True)
    assert twse.rate_limit_per_second <= Decimal("0.5") and twse.rate_limit_burst == 1
    assert "data.gov.tw/license" in (twse.note or "")


def test_the_twse_slots_run_three_times_a_day_in_singapore_time() -> None:
    sgt = ZoneInfo("Asia/Singapore")
    saturday_dawn = datetime(2026, 10, 24, 6, 0, tzinfo=sgt)
    assert TWSE.next_after(saturday_dawn) == datetime(2026, 10, 24, 7, 40, tzinfo=sgt)
    assert TWSE.next_after(datetime(2026, 10, 24, 7, 40, tzinfo=sgt)) == datetime(
        2026, 10, 24, 9, 40, tzinfo=sgt
    )
    assert TWSE.next_after(datetime(2026, 10, 24, 21, 0, tzinfo=sgt)) == datetime(
        2026, 10, 25, 7, 40, tzinfo=sgt
    )
    assert SCHEDULES["twse_openapi"] is TWSE
