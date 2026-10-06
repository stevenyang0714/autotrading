"""A filing's own XBRL instance (ADR-021): parsing, company-facts shape, class sums."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from autotrading.adapters.sec.instance import (
    as_companyfacts,
    class_sums,
    instance_url,
    parse_instance,
)
from autotrading.adapters.sec.parsing import load_companyfacts, select_values

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sec"
META_10K = "0001628280-26-003942"
AAPL_10K = "0000320193-25-000079"


def instance(contexts: str, facts: str, year: str = "2025") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:us-gaap="http://fasb.org/us-gaap/{year}" xmlns:dei="http://xbrl.sec.gov/dei/{year}"
  xmlns:goog="http://www.abc.xyz/{year}">
  <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="usdPerShare"><xbrli:divide>
    <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide></xbrli:unit>
  {contexts}
  {facts}
</xbrli:xbrl>""".encode()


def ctx(
    cid: str, when: str, member: str | None = None, axis: str = "us-gaap:StatementClassOfStockAxis"
) -> str:
    segment = (
        f'<xbrli:segment><xbrldi:explicitMember dimension="{axis}">{member}'
        "</xbrldi:explicitMember></xbrli:segment>"
        if member
        else ""
    )
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
        f"{segment}</xbrli:entity><xbrli:period><xbrli:instant>{when}</xbrli:instant>"
        "</xbrli:period></xbrli:context>"
    )


def test_instance_url_is_the_primary_document_with_htm_xml() -> None:
    assert instance_url("0000320193", AAPL_10K, "aapl-20250927.htm") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927_htm.xml"
    )


def test_units_nil_values_duplicates_and_dated_taxonomies() -> None:
    facts = parse_instance(
        instance(
            ctx("c1", "2019-06-30") + '<xbrli:context id="d1"><xbrli:entity>'
            '<xbrli:identifier scheme="x">1</xbrli:identifier>'
            "</xbrli:entity><xbrli:period><xbrli:startDate>2019-01-01</xbrli:startDate>"
            "<xbrli:endDate>2019-06-30</xbrli:endDate></xbrli:period></xbrli:context>",
            '<us-gaap:Assets contextRef="c1" unitRef="usd" decimals="-6">'
            "97334000000</us-gaap:Assets>"
            '<us-gaap:Assets contextRef="c1" unitRef="usd" decimals="-9">'
            "97000000000</us-gaap:Assets>"
            '<us-gaap:EarningsPerShareDiluted contextRef="d1" unitRef="usdPerShare" decimals="2">'
            "2.42</us-gaap:EarningsPerShareDiluted>"
            '<us-gaap:CommercialPaper contextRef="c1" unitRef="usd" xsi:nil="true"/>'
            '<dei:EntityRegistrantName contextRef="d1">Meta</dei:EntityRegistrantName>',
            year="2019-01-31",
        )
    )
    by_concept = {f.concept: f for f in facts}
    assert set(by_concept) == {"us-gaap:Assets", "us-gaap:EarningsPerShareDiluted"}
    assert by_concept["us-gaap:Assets"].value == Decimal(97334000000)  # most precise kept
    eps = by_concept["us-gaap:EarningsPerShareDiluted"]
    assert (eps.unit, eps.context.start, eps.context.end) == (
        "USD/shares",
        date(2019, 1, 1),
        date(2019, 6, 30),
    )


def test_standard_common_classes_are_added_when_no_total_is_reported() -> None:
    facts = parse_instance(
        instance(
            ctx("a", "2025-12-31", "us-gaap:CommonClassAMember")
            + ctx("b", "2025-12-31", "us-gaap:CommonClassBMember"),
            '<us-gaap:CommonStockSharesOutstanding contextRef="a" unitRef="shares" decimals="-6">'
            "2187000000</us-gaap:CommonStockSharesOutstanding>"
            '<us-gaap:CommonStockSharesOutstanding contextRef="b" unitRef="shares" decimals="-6">'
            "343000000</us-gaap:CommonStockSharesOutstanding>",
        )
    )
    result = class_sums(facts, "x", "10-K", date(2026, 1, 29))
    assert result.findings == []
    [value] = result.values
    assert (value.metric_id, value.value, value.period_end, value.concept) == (
        "shares_outstanding",
        Decimal(2530000000),
        date(2025, 12, 31),
        "us-gaap:CommonStockSharesOutstanding (sum of classes)",
    )


def test_a_custom_class_member_needs_the_filing_to_confirm_the_set() -> None:
    classes = (
        ctx("a", "2026-01-28", "us-gaap:CommonClassAMember")
        + ctx("b", "2026-01-28", "us-gaap:CommonClassBMember")
        + ctx("c", "2026-01-28", "goog:CapitalClassCMember")
    )
    cover = (
        '<dei:EntityCommonStockSharesOutstanding contextRef="a" unitRef="shares" decimals="-6">'
        "5822000000</dei:EntityCommonStockSharesOutstanding>"
        '<dei:EntityCommonStockSharesOutstanding contextRef="b" unitRef="shares" decimals="-6">'
        "837000000</dei:EntityCommonStockSharesOutstanding>"
        '<dei:EntityCommonStockSharesOutstanding contextRef="c" unitRef="shares" decimals="-6">'
        "5438000000</dei:EntityCommonStockSharesOutstanding>"
    )
    unconfirmed = class_sums(
        parse_instance(instance(classes, cover)), "x", "10-K", date(2026, 2, 5)
    )
    assert unconfirmed.values == []
    assert "not confirmed" in unconfirmed.findings[0]

    # The balance sheet confirms A + B + C is all common stock: 5,822 + 837 + 5,429 = 12,088.
    balance = (
        ctx("t", "2025-12-31")
        + ctx("ba", "2025-12-31", "us-gaap:CommonClassAMember")
        + ctx("bb", "2025-12-31", "us-gaap:CommonClassBMember")
        + ctx("bc", "2025-12-31", "goog:CapitalClassCMember")
    )
    totals = "".join(
        f'<us-gaap:CommonStockSharesOutstanding contextRef="{c}" unitRef="shares" decimals="-6">'
        f"{v}</us-gaap:CommonStockSharesOutstanding>"
        for c, v in [("t", 12088000000), ("ba", 5822000000), ("bb", 837000000), ("bc", 5429000000)]
    )
    confirmed = class_sums(
        parse_instance(instance(classes + balance, cover + totals)), "x", "10-K", date(2026, 2, 5)
    )
    assert confirmed.findings == []
    assert [(v.metric_id, v.value) for v in confirmed.values] == [
        ("shares_outstanding_cover", Decimal(12097000000))
    ]  # the balance-sheet date has a total, so only the cover is added


def test_meta_10k_share_counts_are_the_sum_of_class_a_and_b() -> None:
    facts = parse_instance((FIXTURES / f"{META_10K}_instance.xml").read_bytes())
    result = class_sums(facts, META_10K, "10-K", date(2026, 1, 29))
    found = {(v.metric_id, v.period_end): v.value for v in result.values}
    assert found[("shares_outstanding", date(2025, 12, 31))] == Decimal(2530000000)
    assert found[("shares_outstanding_cover", date(2026, 1, 23))] == Decimal(2529555464)
    assert result.findings == []


def test_apple_10k_instance_matches_company_facts_for_that_filing() -> None:
    facts = parse_instance((FIXTURES / f"{AAPL_10K}_instance.xml").read_bytes())
    from_instance = {
        (v.metric_id, v.period_start, v.period_end): v.value
        for v in select_values(as_companyfacts(facts, AAPL_10K, "10-K", date(2025, 10, 31)))
    }
    companyfacts = load_companyfacts((FIXTURES / "companyfacts_CIK0000320193.json").read_bytes())
    reported = {
        (v.metric_id, v.period_start, v.period_end): v.value
        for v in select_values(companyfacts)
        if v.accession == AAPL_10K
    }
    assert from_instance[("revenue", date(2024, 9, 29), date(2025, 9, 27))] == Decimal(416161000000)
    assert reported.items() <= from_instance.items()
    assert class_sums(facts, AAPL_10K, "10-K", date(2025, 10, 31)).values == []
