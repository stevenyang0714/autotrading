# ruff: noqa: RUF001  (issuers' sentences keep their typographic quotes and dashes)
"""Buyback record and announcement events (M1.4a, ADR-025)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from autotrading.domain.buyback import (
    AnnouncementSource,
    buyback_record,
    close_on,
    events,
)
from autotrading.domain.provenance import end_of_day
from autotrading.domain.splits import Split
from autotrading.domain.valuation import Close, Valued


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date
    reported_at: datetime


AT = datetime(2026, 3, 1, tzinfo=UTC)


def d(text: str) -> date:
    return date.fromisoformat(text)


def year(metric: str, y: int, value: int) -> F:
    return F(
        metric, Decimal(value), date(y, 1, 1), date(y, 12, 31), datetime(y + 1, 2, 1, tzinfo=UTC)
    )


def instant(metric: str, y: int, value: int, reported: datetime | None = None) -> F:
    return F(
        metric,
        Decimal(value),
        None,
        date(y, 12, 31),
        reported or datetime(y + 1, 2, 1, tzinfo=UTC),
    )


def company(buyback: int = 60, net_debt_2025: int = 100) -> list[F]:
    """FY2024 and FY2025 (calendar years), shares falling from 1,000 to 960."""
    return [
        *(
            year(m, y, v)
            for m, y, v in (
                ("revenue", 2024, 1000),
                ("revenue", 2025, 1100),
                ("net_income", 2024, 100),
                ("net_income", 2025, 110),
                ("operating_cash_flow", 2024, 140),
                ("operating_cash_flow", 2025, 150),
                ("capex", 2024, 40),
                ("capex", 2025, 50),
                ("share_repurchases", 2024, 50),
                ("share_repurchases", 2025, buyback),
                ("shares_repurchased", 2024, 30),
                ("shares_repurchased", 2025, 45),
                ("stock_based_compensation", 2024, 10),
                ("stock_based_compensation", 2025, 15),
            )
        ),
        instant("shares_outstanding", 2023, 1000),
        instant("shares_outstanding", 2024, 1000),
        instant("shares_outstanding", 2025, 960),
        instant("long_term_debt_noncurrent", 2024, 200),
        instant("cash", 2024, 150),  # net debt 50
        instant("long_term_debt_noncurrent", 2025, 200 + net_debt_2025),
        instant("cash", 2025, 200),
    ]


def close(day: str, value: str = "20") -> Close:
    return Close(d(day), Decimal(value), "end_of_day", end_of_day(d(day)))


CLOSES = [close("2025-12-31"), close("2024-12-31", "16")]


def fy2025(
    facts: list[F], closes: list[Close] = CLOSES, splits: list[Split] | None = None
) -> dict[str, Valued[F]]:
    record = buyback_record(facts, closes, AT, splits or [])
    index = [p.end for p in record.periods].index(d("2025-12-31"))
    return {metric: values[index] for _, metric, _, values in record.rows}


def test_authorization_actual_repurchase_and_net_reduction_are_separate_values() -> None:
    fy = fy2025(company())
    expected = {
        "share_repurchases": "60",
        "shares_repurchased": "45",
        "buyback_intensity": "0.31",  # 60 / (20 x 960)
        "repurchase_to_fcf": "60.00",  # 60 / (150 - 50)
        "sbc_offset": "25.00",  # 15 / 60
        "net_share_reduction": "40",  # 1,000 - 960
        "net_share_reduction_pct": "4.00",
    }
    assert {m: str(fy[m].value) for m in expected} == expected
    cap = fy["buyback_intensity"].inputs[1]
    assert (cap.name, cap.value) == ("market_cap", Decimal(19200))
    assert cap.note is not None and "close 2025-12-31" in cap.note


def test_debt_funded_only_when_net_debt_rises_and_buybacks_exceed_fcf() -> None:
    # Net debt rises from 50 to 100 in 2025; FCF is 100.
    assert fy2025(company(buyback=120))["debt_funded_buyback"].value == Decimal(1)
    assert fy2025(company(buyback=60))["debt_funded_buyback"].value == Decimal(0)  # within FCF
    unchanged_debt = fy2025(company(buyback=120, net_debt_2025=0))
    assert unchanged_debt["debt_funded_buyback"].value == Decimal(0)


def test_no_close_near_the_period_end_leaves_intensity_unavailable() -> None:
    fy = fy2025(company(), closes=[close("2025-12-01")])
    assert fy["buyback_intensity"].detail == "not reported: end-of-day close by 2025-12-31"
    assert fy["share_repurchases"].value == Decimal(60)  # the rest stands
    assert close_on([Close(d("2025-12-31"), Decimal(1), "fixture", AT)], d("2025-12-31")) is None


def test_share_counts_are_compared_on_one_split_basis() -> None:
    # A 2-for-1 split in mid-2025: the 2024 count (reported before it) doubles to compare.
    split = Split(d("2025-06-02"), Decimal(1), Decimal(2))
    facts = [f for f in company() if f.metric_id != "shares_outstanding"]
    facts += [
        instant("shares_outstanding", 2024, 1000),  # reported 2025-02-01, before the split
        instant("shares_outstanding", 2025, 1960),  # reported 2026-02-01, after it
    ]
    fy = fy2025(facts, splits=[split])
    assert fy["net_share_reduction"].value == Decimal(40)  # 2,000 - 1,960
    before = fy["net_share_reduction"].inputs[0]
    assert before.note is not None and "factor 2" in before.note


def test_missing_shares_outstanding_is_named() -> None:
    facts = [
        f
        for f in company()
        if not (f.metric_id == "shares_outstanding" and f.period_end.year == 2024)
    ]
    fy = fy2025(facts)
    assert fy["net_share_reduction"].detail == "not reported: shares outstanding on 2024-12-31"


def source(
    kind: str,
    amount: int,
    published: str,
    channel: str = "sec_8k",
    stated: str | None = None,
    accession: str | None = "0000000000-26-000001",
    sentence: str = "s",
) -> AnnouncementSource:
    return AnnouncementSource(
        channel=channel,  # type: ignore[arg-type]
        kind=kind,
        amount=Decimal(amount) * 10**9,
        remaining_amount=None,
        stated_date=d(stated) if stated else None,
        sentence=sentence,
        url=f"https://example.com/{channel}/{published}",
        published_at=datetime.fromisoformat(published).replace(tzinfo=UTC),
        accession=accession if channel == "sec_8k" else None,
    )


def test_one_event_per_kind_and_amount_with_every_source() -> None:
    sources = [
        source("increase", 60, "2025-08-27T20:00:00", sentence="8-K"),
        source("increase", 60, "2025-08-27T20:05:00", channel="press_release", sentence="release"),
        # A later filing repeating the stated date is the same event.
        source(
            "increase",
            60,
            "2025-11-19T21:00:00",
            stated="2025-08-26",
            accession="0000000000-25-000228",
        ),
        source("remaining", 15, "2025-08-27T20:00:00"),
        source("increase", 150, "2026-09-28T11:00:00", channel="press_release"),  # after T
    ]
    found = events(sources, AT)
    assert [(e.kind, e.amount / 10**9, e.day) for e in found] == [  # newest first
        ("remaining", 15, d("2025-08-27")),
        ("increase", 60, d("2025-08-26")),
    ]
    increase = found[1]
    assert len(increase.sources) == 3
    assert increase.first_published_at == datetime(2025, 8, 27, 20, tzinfo=UTC)


def test_a_co_filed_8k_counts_once() -> None:
    twice = [
        source("plan", 20, "2025-08-01T12:00:00", sentence="plan to repurchase $20 billion"),
        source("plan", 20, "2025-08-01T12:00:00", sentence="plan to repurchase $20 billion"),
    ]
    assert len(events(twice, AT)[0].sources) == 1


def test_the_same_amount_a_year_apart_is_two_events() -> None:
    sources = [
        source("increase", 100, "2025-05-01T20:00:00"),
        source("increase", 100, "2026-04-30T20:00:00", accession="0000000000-26-000011"),
    ]
    assert len(events(sources, datetime(2026, 5, 1, tzinfo=UTC) + timedelta(days=1))) == 2


def test_a_quarterly_restatement_of_the_same_sentence_is_the_same_event() -> None:
    sentence = (
        "The Firm’s Board of Directors authorized a new common share repurchase program for up "
        "to $30 billion."
    )
    jpm = [
        source(
            "new", 30, "2021-01-15T12:00:00", sentence=sentence, accession="0000019617-21-000001"
        ),
        source(
            "new", 30, "2021-04-14T12:00:00", sentence=sentence, accession="0000019617-21-000002"
        ),
        source(
            "new", 30, "2021-07-13T12:00:00", sentence=sentence, accession="0000019617-21-000003"
        ),
    ]
    found = events(jpm, AT)
    assert [(e.day, len(e.sources)) for e in found] == [(d("2021-01-15"), 3)]
    # Apple renews a $100 billion increase each spring in the same words: two events.
    words = (
        "The board of directors has also authorized an additional program to repurchase up to "
        "$100 billion."
    )
    apple = [
        source("increase", 100, "2025-05-01T20:00:00", sentence=words),
        source(
            "increase", 100, "2026-04-30T20:00:00", sentence=words, accession="0000320193-26-000011"
        ),
    ]
    assert len(events(apple, datetime(2026, 5, 2, tzinfo=UTC))) == 2
