"""FinMind (M3.7b, ADR-040): the parsers on recorded responses, their agreement with the
recorded TWSE files on the same session (TW19), the ex-dividend decoding (TW20), the client's
allowed datasets, envelope check and quota cooldown (TW16, TW22), and the source entry. M3.11
(ADR-042 SC6): what `spread` is on an ex-date."""

from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import httpx2 as httpx
import pytest

from autotrading.adapters.finmind.client import (
    ALLOWED_DATASETS,
    DIVIDENDS,
    INSTITUTIONAL,
    MARGIN,
    PER,
    PRICE,
    SHAREHOLDING,
    FinMindClient,
    FinMindCooldownError,
    FinMindQuotaError,
    FinMindRequestError,
    MemoryCooldown,
    public_url,
)
from autotrading.adapters.finmind.daily import FinMindFlowsJob
from autotrading.config_sync import load_sources
from autotrading.domain.finmind import (
    FinMindFormatError,
    dividend_results,
    flow_days,
    margin_days,
    price_rows,
    shareholding_days,
    valuation_rows,
)
from autotrading.domain.twse import day_rows as twse_day_rows
from autotrading.domain.twse import margin_rows as twse_margin_rows
from autotrading.domain.twse import valuation_rows as twse_valuation_rows
from autotrading.ingestion.job import Window
from autotrading.ingestion.schedule import FINMIND, SCHEDULES
from autotrading.settings import get_settings
from tests.finmind_replay import payload, price_history
from tests.twse_replay import payload as twse_payload

CONFIG = Path(get_settings().resolved_config_dir())
D1 = date(2026, 10, 21)


def test_the_recorded_files_parse_with_finmind_field_names() -> None:
    prices = {r.session: r for r in price_rows(payload("2330", PRICE))}
    assert len(prices) == 15 and prices[D1].close == Decimal("2420.0")
    assert prices[D1].change == Decimal("15.0") and prices[D1].volume == Decimal(27095005)
    margin = {d.session: d for d in margin_days(payload("2330", MARGIN))}
    assert margin[D1].values["margin_balance"] == Decimal(35330)
    assert margin[D1].values["short_balance_previous"] == Decimal(14)
    per = {r.session: r for r in valuation_rows(payload("2330", PER))}
    assert (per[D1].pe, per[D1].pb, per[D1].dividend_yield) == (
        Decimal("28.05"),
        Decimal("9.76"),
        Decimal("0.91"),
    )
    holdings = {d.session: d for d in shareholding_days(payload("2330", SHAREHOLDING))}
    assert holdings[D1].values["foreign_ratio"] == Decimal("68.63")
    assert holdings[D1].values["shares_issued"] == Decimal(25932370067)


def test_finmind_agrees_with_the_twse_files_on_the_same_session() -> None:
    """TW19: the units are the TWSE units (shares, lots, multiples), proven on 2026-10-21."""
    twse_day = {r.code: r for r in twse_day_rows(twse_payload("d1", "STOCK_DAY_ALL"))}["2330"]
    finmind_day = {r.session: r for r in price_rows(payload("2330", PRICE))}[D1]
    assert (
        finmind_day.close,
        finmind_day.volume,
        finmind_day.transactions,
        finmind_day.change,
    ) == (
        twse_day.close,
        twse_day.volume,
        twse_day.transactions,
        twse_day.change,
    )
    twse_margin = {r.code: r for r in twse_margin_rows(twse_payload("d1", "MI_MARGN"))}["2330"]
    finmind_margin = {d.session: d for d in margin_days(payload("2330", MARGIN))}[D1]
    assert dict(finmind_margin.values) == dict(twse_margin.values)
    twse_per = {r.code: r for r in twse_valuation_rows(twse_payload("d1", "BWIBBU_d"))}["2330"]
    finmind_per = {r.session: r for r in valuation_rows(payload("2330", PER))}[D1]
    assert (finmind_per.pe, finmind_per.pb, finmind_per.dividend_yield) == (
        twse_per.pe,
        twse_per.pb,
        twse_per.dividend_yield,
    )


def test_institutional_rows_are_summed_per_session_in_shares() -> None:
    days, notes = flow_days(payload("2330", INSTITUTIONAL))
    assert notes == [] and len(days) == 15
    day = {d.session: d for d in days}[D1]
    assert day.groups == (
        "Dealer_Hedging",
        "Dealer_self",
        "Foreign_Dealer_Self",
        "Foreign_Investor",
        "Investment_Trust",
    )
    v = day.values
    assert v["inst_foreign_net"] == v["inst_foreign_buy"] - v["inst_foreign_sell"]
    assert v["inst_total_net"] == v["inst_foreign_net"] + v["inst_trust_net"] + v["inst_dealer_net"]
    # a day without the foreign investor row is incomplete: not stored, said so
    rows = [r for r in payload("2330", INSTITUTIONAL)["data"] if r["name"] != "Foreign_Investor"]
    days, notes = flow_days({"msg": "success", "status": 200, "data": rows})
    assert days == [] and len(notes) == 15


def test_ex_dividend_results_are_decoded_from_the_prices() -> None:
    """TW20: 息 rows must reproduce the reference price; 權 rows give the ratio from
    before / reference; a combined row is left out."""
    fubon = {r.ex_date: r for r in dividend_results(payload("2881", DIVIDENDS))}
    cash = fubon[date(2026, 7, 1)]
    assert cash.accepted and cash.kind == "息" and cash.cash == Decimal("4.25")
    assert cash.stock_ratio is None
    stock = fubon[date(2021, 9, 6)]  # before 84.8, reference 77.09: a 10% stock dividend
    assert stock.accepted and stock.kind == "權" and stock.stock_ratio == Decimal("0.1000")
    assert fubon[date(2022, 9, 22)].stock_ratio == Decimal("0.0502")  # 56.5 / 53.8 - 1
    assert sum(r.accepted for r in fubon.values()) == len(fubon) == 16
    # the stated 權 amount is a price drop, not a ratio: never read as one
    assert stock.cash is None
    broken = dict(payload("2881", DIVIDENDS)["data"][0], stock_and_cache_dividend=5.0)
    (rejected,) = dividend_results({"msg": "success", "status": 200, "data": [broken]})
    assert not rejected.accepted and "does not reproduce" in (rejected.note or "")
    combined = dict(payload("2881", DIVIDENDS)["data"][0], stock_or_cache_dividend="權息")
    (skipped,) = dividend_results({"msg": "success", "status": 200, "data": [combined]})
    assert not skipped.accepted and "cannot be split" in (skipped.note or "")


def test_the_spread_is_zero_on_an_ex_date_so_its_reference_price_comes_from_the_results() -> None:
    """ADR-042 SC6, the check behind the listed backfill: on every recorded ex-date FinMind's
    `spread` is 0 (not the change against the reference price) while the close moved; on every
    other session it is the change against the previous close. The ex-dividend results name the
    day's previous close and reference price, so the screens' return across an ex-date comes
    from them."""
    for code in ("2330", "2881"):
        rows = price_rows(price_history(code)[0])
        results = {r.ex_date: r for r in dividend_results(payload(code, DIVIDENDS))}
        ex_dates = 0
        for before, row in pairwise(rows):
            assert row.close is not None and row.change is not None
            if row.session in results:
                ex_dates += 1
                assert row.change == 0 and row.close != before.close
                assert results[row.session].before_price == before.close
                assert 0 < results[row.session].reference_price < before.close
            else:
                assert row.close - row.change == before.close
        assert ex_dates == (6 if code == "2330" else 5)


def test_a_flows_run_fetches_flow_datasets_only() -> None:
    def job(**params: object) -> FinMindFlowsJob:
        return FinMindFlowsJob({"codes": ["2303"], **params}, Window())

    assert job().datasets == (INSTITUTIONAL, SHAREHOLDING)
    assert job(datasets=[INSTITUTIONAL]).datasets == (INSTITUTIONAL,)
    with pytest.raises(ValueError, match="not flow datasets"):
        _ = job(datasets=[PRICE]).datasets


def test_a_changed_dataset_fails_instead_of_storing_half() -> None:
    rows = payload("2330", PRICE)["data"]
    del rows[0]["close"]
    with pytest.raises(FinMindFormatError, match="close"):
        price_rows({"msg": "success", "status": 200, "data": rows})
    with pytest.raises(FinMindFormatError, match="envelope"):
        margin_days([])


def test_the_client_reaches_six_datasets_only_and_checks_the_envelope() -> None:
    assert len(ALLOWED_DATASETS) == 6
    url = public_url(PRICE, "2330", date(2026, 10, 1), date(2026, 10, 22))
    assert url.startswith("https://api.finmindtrade.com/api/v4/data?")
    assert "token" not in url
    with pytest.raises(ValueError, match="not one of the FinMind datasets"):
        public_url("TaiwanStockNews", "2330", date(2026, 10, 1), date(2026, 10, 22))

    def error_body(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"msg": "no data", "status": 400, "data": []})

    with (
        FinMindClient(transport=httpx.MockTransport(error_body), sleep=lambda _: None) as client,
        pytest.raises(FinMindRequestError, match="FinMind error"),
    ):
        client.get(PRICE, "2330", date(2026, 10, 1), date(2026, 10, 22), lambda: None)


def test_a_quota_error_starts_a_cooldown_and_is_not_retried() -> None:
    """TW16: a 402 or 403 is one request, then 35 minutes of silence shared by every job."""
    calls: list[str] = []

    def over_quota(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(402, json={"msg": "Requests reach the upper limit", "status": 402})

    cooldown = MemoryCooldown()
    with FinMindClient(
        cooldown=cooldown, transport=httpx.MockTransport(over_quota), sleep=lambda _: None
    ) as client:
        with pytest.raises(FinMindQuotaError, match="cooling down"):
            client.get(PRICE, "2330", date(2026, 10, 1), date(2026, 10, 22), lambda: None)
        assert len(calls) == 1 and cooldown.active()
        with pytest.raises(FinMindCooldownError, match="not sent"):
            client.get(MARGIN, "2330", date(2026, 10, 1), date(2026, 10, 22), lambda: None)
        assert len(calls) == 1  # nothing reached the network during the cooldown


def test_the_source_is_tier_two_under_the_free_tier_cap() -> None:
    sources = {s.id: s for s in load_sources(CONFIG / "sources.yaml").sources}
    finmind = sources["finmind"]
    assert (finmind.tier, finmind.license_status, finmind.enabled) == (2, "licensed_personal", True)
    assert finmind.rate_limit_per_second * 3600 < 300 and finmind.rate_limit_burst == 1
    assert "資料來源：FinMind" in (finmind.note or "")
    assert SCHEDULES["finmind"] is FINMIND and (FINMIND.hour, FINMIND.minute) == (21, 30)
