"""Filing reconciliation statuses and checks (ADR-021)."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from autotrading.domain.reconciliation import (
    Result,
    Stored,
    fact_items,
    identity_items,
    quarter_items,
    rounding_unit,
    split_items,
)

FY = ("revenue", date(2024, 9, 29), date(2025, 9, 27))
NI = ("net_income", date(2024, 9, 29), date(2025, 9, 27))
CASH = ("cash", None, date(2025, 9, 27))
EPS = ("eps_diluted", date(2024, 9, 29), date(2025, 9, 27))
TEN_K = "0000320193-25-000079"


def test_fact_statuses() -> None:
    filing = {FY: Decimal(416161), NI: Decimal(112010), CASH: Decimal(35934), EPS: Decimal("7.46")}
    then = {
        FY: Stored(Decimal(416161), TEN_K),
        NI: Stored(Decimal(112011), TEN_K),  # differs: mismatch
        EPS: Stored(Decimal("7.46"), TEN_K),
    }  # CASH unknown then: missing
    now = {**then, EPS: Stored(Decimal("7.40"), "later-10-K/A")}  # restated later
    extra_key = ("capex", date(2024, 9, 29), date(2025, 9, 27))
    items = fact_items(filing, then, now, under_accession=[FY, extra_key])
    statuses = {(i.metric_id, i.status) for i in items}
    assert statuses == {
        ("revenue", "match"),
        ("net_income", "mismatch"),
        ("cash", "missing"),
        ("eps_diluted", "restated_later"),
        ("capex", "extra"),
    }
    result = Result(items)
    assert not result.passed
    assert (result.count("mismatch"), result.count("restated_later")) == (1, 1)


def test_restated_later_alone_passes() -> None:
    items = fact_items(
        {FY: Decimal(1)}, {FY: Stored(Decimal(1), "a")}, {FY: Stored(Decimal(2), "b")}, [FY]
    )
    assert [i.status for i in items] == ["restated_later"]
    assert Result(items).passed


def test_the_balance_identity_on_dates_the_filing_reports_both() -> None:
    day = date(2025, 9, 27)
    items = identity_items(
        {
            ("us-gaap:Assets", day): Decimal(359241),
            ("us-gaap:LiabilitiesAndStockholdersEquity", day): Decimal(359241),
            ("us-gaap:Assets", date(2024, 9, 28)): Decimal(364980),  # no total that day: skipped
        }
    )
    assert [(i.metric_id, i.period_end, i.status) for i in items] == [("balance_sheet", day, "ok")]
    broken = identity_items(
        {
            ("us-gaap:Assets", day): Decimal(1),
            ("us-gaap:LiabilitiesAndStockholdersEquity", day): Decimal(2),
        }
    )
    assert [i.status for i in broken] == ["fail"]


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date


def test_quarters_from_stored_year_to_date_values_against_the_filing() -> None:
    start = date(2024, 9, 29)
    stored = [
        F("revenue", Decimal(391035), date(2023, 10, 1), start - timedelta(days=1)),  # FY2024
        F("revenue", Decimal(124300), start, date(2024, 12, 28)),
        F("revenue", Decimal(219659), start, date(2025, 3, 29)),
    ]
    q2 = ("revenue", date(2024, 12, 29), date(2025, 3, 29))
    [ok] = quarter_items(stored, {q2: Decimal(95359)})
    assert (ok.status, ok.stored_value) == ("ok", Decimal(95359))
    [bad] = quarter_items(stored, {q2: Decimal(95362)})
    assert bad.status == "fail"


def test_a_quarter_one_rounding_unit_off_is_within_rounding() -> None:
    # Meta Q2 2025 operating income: reported 20,441M; six months - Q1 = 20,442M.
    start = date(2025, 1, 1)
    stored = [
        F("operating_income", Decimal(69380000000), date(2024, 1, 1), date(2024, 12, 31)),
        F("operating_income", Decimal(17555000000), start, date(2025, 3, 31)),
        F("operating_income", Decimal(37997000000), start, date(2025, 6, 30)),
    ]
    key = ("operating_income", date(2025, 4, 1), date(2025, 6, 30))
    [item] = quarter_items(stored, {key: Decimal(20441000000)})
    assert item.status == "ok" and "within rounding" in (item.detail or "")
    assert rounding_unit(Decimal(20441000000), Decimal(37997000000)) == Decimal(1000000)
    assert rounding_unit(Decimal("7.46")) == 1


def test_unexplained_splits_flag_the_reconciliation() -> None:
    items = split_items(["eps_diluted 2019-09-28: 11.89 became 2.97, a ratio of about 4"])
    assert [(i.check, i.status) for i in items] == [("split", "flag")]
    assert not Result(items).passed
