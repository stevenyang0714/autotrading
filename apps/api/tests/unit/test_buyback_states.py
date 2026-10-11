"""Buyback states and the Buyback Quality Score (M1.4b, ADR-025, errata E7)."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from autotrading.domain.buyback import AnnouncementSource, Event
from autotrading.domain.buyback_states import (
    DcfContext,
    Evidence,
    RulesFile,
    assess,
    linear,
)
from autotrading.domain.provenance import end_of_day
from autotrading.domain.valuation import Close, select_price

RULES_PATH = Path(__file__).resolve().parents[4] / "config" / "buyback_rules.yaml"
# A released rule set never changes (ADR-025 B4): a change to its content needs a new
# rule_version, and its hash is added here.
RELEASED = {
    "0.1.0": "ce338c414407608f2844fde3d265bfc96d114586a23efbfb13eb9a42310b5465",
    "0.2.0": "7966ec40c8503ac2cb5347fea3d48f8c938a48cb6ecbc3b422a20432b33ae7d0",
}


@dataclass(frozen=True)
class F:
    metric_id: str
    value: Decimal
    period_start: date | None
    period_end: date
    reported_at: datetime


AT = datetime(2026, 8, 15, 12, tzinfo=UTC)
B = Decimal(1)


def d(text: str) -> date:
    return date.fromisoformat(text)


def reported(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def ytd(metric: str, year: int, quarters: tuple[int, ...]) -> list[F]:
    """Year-to-date values of a calendar year: Q1, H1, 9M and the year, as far as given."""
    start, ends = date(year, 1, 1), ("03-31", "06-30", "09-30", "12-31")
    total, out = 0, []
    for i, value in enumerate(quarters):
        total += value
        end = d(f"{year}-{ends[i]}")
        out.append(
            F(metric, Decimal(total), start, end, reported(year + (i == 3), (i * 3 + 5) % 12))
        )
    return out


def instant(metric: str, day: str, value: int) -> F:
    end = d(day)
    return F(
        metric,
        Decimal(value),
        None,
        end,
        datetime.combine(end, datetime.min.time(), UTC) + timedelta(days=40),
    )


def quarter(metric: str, start: str, end: str, value: int) -> F:
    return F(
        metric,
        Decimal(value),
        d(start),
        d(end),
        datetime.combine(d(end), datetime.min.time(), UTC) + timedelta(days=40),
    )


def company(q2_2026_buyback: int = 120) -> list[F]:
    """FY2023-FY2025 and the first half of 2026; shares falling every year."""
    facts: list[F] = []
    for metric, by_year in {
        "revenue": {2023: (900,) * 4, 2024: (950,) * 4, 2025: (1000,) * 4, 2026: (1050, 1050)},
        "net_income": {2023: (85,) * 4, 2024: (90,) * 4, 2025: (100,) * 4, 2026: (110, 110)},
        "operating_cash_flow": {
            2023: (125,) * 4,
            2024: (137, 137, 138, 138),
            2025: (150,) * 4,
            2026: (160, 160),
        },
        "capex": {2023: (25,) * 4, 2024: (27, 27, 28, 28), 2025: (30,) * 4, 2026: (30, 30)},
        "share_repurchases": {
            2023: (75,) * 4,
            2024: (85, 85, 90, 90),
            2025: (80, 90, 100, 110),
            2026: (100, q2_2026_buyback),
        },
    }.items():
        for year, values in by_year.items():
            facts += ytd(metric, year, values)
    for day, count in (
        ("2022-12-31", 1030),
        ("2023-12-31", 1015),
        ("2024-12-31", 1000),
        ("2025-06-30", 990),
        ("2025-12-31", 975),
        ("2026-06-30", 960),
    ):
        facts.append(instant("shares_outstanding", day, count))
    for day, debt, cash in (
        ("2024-12-31", 300, 210),
        ("2025-06-30", 300, 200),
        ("2025-12-31", 300, 198),
        ("2026-06-30", 300, 195),
    ):
        facts += [instant("long_term_debt_noncurrent", day, debt), instant("cash", day, cash)]
    # Weighted diluted shares: the year, the year to date and the second quarter alone.
    facts += [
        quarter("diluted_shares", start, end, value)
        for start, end, value in (
            ("2025-01-01", "2025-12-31", 995),
            ("2025-01-01", "2025-03-31", 1005),
            ("2025-01-01", "2025-06-30", 1002),
            ("2025-04-01", "2025-06-30", 1000),
            ("2026-01-01", "2026-03-31", 975),
            ("2026-01-01", "2026-06-30", 972),
            ("2026-04-01", "2026-06-30", 970),
        )
    ]
    return facts


def close(day: str, value: str, status: str = "end_of_day") -> Close:
    return Close(d(day), Decimal(value), status, end_of_day(d(day)))


CLOSES = [close("2026-06-30", "20"), close("2026-08-14", "25")]


def source(kind: str, amount: int, day: str, remaining: int | None = None) -> AnnouncementSource:
    return AnnouncementSource(
        channel="sec_8k",
        kind=kind,
        amount=Decimal(amount),
        remaining_amount=Decimal(remaining) if remaining is not None else None,
        stated_date=None,
        sentence="s",
        url=f"https://example.com/{day}",
        published_at=datetime.fromisoformat(day).replace(hour=20, tzinfo=UTC),
        accession="0000000000-26-000001",
    )


def event(kind: str, amount: int, day: str, remaining: int | None = None) -> Event:
    return Event(kind, Decimal(amount), d(day), [source(kind, amount, day, remaining)])


INCREASE = event("increase", 500, "2026-04-30")
HISTORY = [(d(f"{2021 + m // 12}-{m % 12 + 1:02d}-28"), Decimal("2.00")) for m in range(66)]
DCF = DcfContext("ok", None, Decimal("27.78"), Decimal(25), Decimal("10.00"), None)


def evidence(
    facts: list[F] | None = None,
    closes: list[Close] | None = None,
    events: list[Event] | None = None,
    **changes: object,
) -> Evidence[F]:
    shown = CLOSES if closes is None else closes
    base = Evidence(
        at=AT,
        facts=company() if facts is None else facts,
        closes=shown,
        splits=[],
        price=select_price(shown, AT),
        events=[INCREASE] if events is None else events,
        announcements_since=d("2021-01-01"),
        fcf_yield_history=HISTORY,
        dcf=DCF,
        benchmark_closes=[],
    )
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def rules() -> RulesFile:
    return RulesFile.model_validate(yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")))


def conditions(result: object) -> dict[str, object]:
    return {c.condition_id: c for c in result.conditions}  # type: ignore[attr-defined]


def test_released_rule_sets_never_change(rules: RulesFile) -> None:
    assert {r.rule_version: r.content_sha256() for r in rules.rule_sets} == RELEASED
    assert rules.active().rule_version == "0.2.0"


def test_a_company_meeting_every_condition_is_a_high_conviction_candidate(
    rules: RulesFile,
) -> None:
    result = assess(rules.active(), evidence())
    assert result.state == "high_conviction"
    found = {c.condition_id: (c.status, c.value) for c in result.conditions}
    assert found == {
        "watch.announcement": ("pass", Decimal(107)),  # days since 2026-04-30
        "watch.remaining": ("fail", None),
        "active.quarter_repurchase": ("pass", Decimal("0.62")),  # 120 / (20 x 960)
        "active.diluted_shares": ("pass", Decimal("-3.00")),  # 970 / 1,000 - 1
        "high_conviction.fcf_funding": ("pass", Decimal("0.86")),  # 430 / 500
        "high_conviction.net_debt": ("pass", Decimal("5.00")),  # 100 -> 105
        "high_conviction.fcf_yield": ("pass", Decimal("1.04")),  # 2.08% / 2.00%
        "high_conviction.dcf_discount": ("fail", Decimal("10.00")),
        "trade_ready.above_average": ("unavailable", None),
        "trade_ready.relative_return": ("unavailable", None),
        "trade_ready.risk_check": ("unavailable", None),
    }
    assert [(lv.level, lv.status) for lv in result.levels] == [
        ("watch", "pass"),
        ("active", "pass"),
        ("high_conviction", "pass"),
        ("trade_ready", "unavailable"),
    ]


def test_an_announcement_alone_never_goes_past_watch(rules: RulesFile) -> None:
    # Acceptance 2: the board allowed buybacks, but no repurchase is reported.
    result = assess(rules.active(), evidence(facts=[]))
    assert result.state == "watch"
    quarter = conditions(result)["active.quarter_repurchase"]
    assert (quarter.status, quarter.detail) == (  # type: ignore[attr-defined]
        "unavailable",
        "not reported: share repurchases",
    )
    # Every other fact can be there: without repurchases nothing gets past WATCH.
    no_buybacks = [f for f in company() if f.metric_id != "share_repurchases"]
    assert assess(rules.active(), evidence(facts=no_buybacks)).state == "watch"


def test_a_quarter_without_repurchases_fails_active(rules: RulesFile) -> None:
    # Meta repurchased nothing in the first half of 2026 after years of buybacks.
    result = assess(rules.active(), evidence(facts=company(q2_2026_buyback=0)))
    assert result.state == "watch"
    quarter = conditions(result)["active.quarter_repurchase"]
    assert (quarter.status, quarter.detail) == (  # type: ignore[attr-defined]
        "fail",
        "no repurchases in the quarter ended 2026-06-30",
    )
    # Even without any close to measure market cap with.
    assert assess(rules.active(), evidence(facts=company(0), closes=[])).state == "watch"


def test_watch_needs_a_recent_announcement_or_a_large_remaining_amount(rules: RulesFile) -> None:
    old = [event("increase", 500, "2025-07-01")]
    assert assess(rules.active(), evidence(events=old)).state == "none"
    # A remaining amount of 2% of market cap or more (24,000 at T) is enough on its own.
    remaining = [event("remaining", 480, "2025-12-01")]
    result = assess(rules.active(), evidence(events=remaining))
    assert conditions(result)["watch.remaining"].value == Decimal("2.00")  # type: ignore[attr-defined]
    assert result.state == "high_conviction"
    # NVIDIA's increase that also states the total remaining.
    nvidia = [event("increase", 150, "2026-08-01", remaining=235)]
    assert conditions(assess(rules.active(), evidence(events=nvidia)))[
        "watch.remaining"
    ].value == Decimal("0.98")  # type: ignore[attr-defined]


def test_before_the_8k_history_a_missing_announcement_is_unavailable(rules: RulesFile) -> None:
    early = evidence(events=[], at=datetime(2021, 6, 30, tzinfo=UTC), facts=[], closes=[])
    announcement = conditions(assess(rules.active(), early))["watch.announcement"]
    assert announcement.status == "unavailable"  # type: ignore[attr-defined]
    assert "8-Ks are read from 2021-01-01 only" in announcement.detail  # type: ignore[attr-defined]


def test_funding_and_valuation_context(rules: RulesFile) -> None:
    # Repurchases above 1.2 x free cash flow: ACTIVE at most.
    heavy = [
        f
        for f in company()
        if not (f.metric_id == "share_repurchases" and f.period_end.year == 2026)
    ] + ytd("share_repurchases", 2026, (300, 400))
    result = assess(rules.active(), evidence(facts=heavy))
    assert conditions(result)["high_conviction.fcf_funding"].status == "fail"  # type: ignore[attr-defined]
    assert result.state == "active"
    # FCF yield below its median and no DCF discount: no valuation context.
    cheap_history = [(day, Decimal("2.50")) for day, _ in HISTORY]
    assert assess(rules.active(), evidence(fcf_yield_history=cheap_history)).state == "active"
    # A DCF discount alone is enough.
    discount = replace(DCF, margin_of_safety=Decimal("20.00"))
    assert (
        assess(rules.active(), evidence(fcf_yield_history=cheap_history, dcf=discount)).state
        == "high_conviction"
    )
    # Too little FCF yield history, and no DCF: unavailable, never a pass.
    short = assess(
        rules.active(),
        evidence(fcf_yield_history=HISTORY[-12:], dcf=replace(DCF, margin_of_safety=None)),
    )
    assert conditions(short)["high_conviction.fcf_yield"].status == "unavailable"  # type: ignore[attr-defined]
    assert short.state == "active"


def test_trade_ready_is_unreachable_even_with_market_confirmation(rules: RulesFile) -> None:
    rising = [
        close(str(d("2026-05-01") + timedelta(days=i)), f"{15 + i / 20:.2f}") for i in range(106)
    ]
    spy = [close(c.day.isoformat(), "500") for c in rising]
    result = assess(rules.active(), evidence(closes=rising, benchmark_closes=spy))
    found = conditions(result)
    assert found["trade_ready.above_average"].status == "pass"  # type: ignore[attr-defined]
    assert found["trade_ready.relative_return"].status == "pass"  # type: ignore[attr-defined]
    assert found["trade_ready.risk_check"].status == "unavailable"  # type: ignore[attr-defined]
    assert result.state == "high_conviction"


def test_score_components_map_linearly_and_any_gap_leaves_the_total_unavailable(
    rules: RulesFile,
) -> None:
    assert linear(Decimal("1.04"), Decimal("0.8"), Decimal("1.2")) == Decimal("60.0")
    assert linear(Decimal("0.21"), Decimal(4), Decimal(0)) == Decimal("94.8")  # lower is better
    assert linear(Decimal(9), Decimal(0), Decimal(4)) == Decimal("100.0")  # clamped
    score = assess(rules.active(), evidence()).score
    assert {c.component: c.score for c in score.components} == {
        "undervaluation": Decimal("60.0"),
        "intensity": Decimal("56.0"),  # 430 / 19,200 = 2.24%
        "fcf_quality": Decimal("100.0"),  # 500 / 420 = 119%
        "balance_sheet": Decimal("94.8"),  # 105 / 500 = 0.21x
        "discipline": Decimal("100.0"),  # 3 of 3 fiscal years
        "share_count": Decimal("100.0"),  # 30 / 990 = 3.03%
    }
    assert score.total == Decimal("77.6")  # (30x60 + 20x56 + 15x100 + 10x94.8 + 10x100 + 10x100)/95
    assert score.label == "default weights, unvalidated"
    gap = assess(rules.active(), evidence(fcf_yield_history=[])).score
    assert gap.total is None and gap.detail == "unavailable: undervaluation"
    assert next(c for c in gap.components if c.component == "intensity").score is not None


def test_a_period_end_market_cap_uses_the_latest_dated_share_count(rules: RulesFile) -> None:
    # B12: no balance-sheet count on the quarter end, only the cover page of the 10-Q before.
    facts = [
        f
        for f in company()
        if not (f.metric_id == "shares_outstanding" and f.period_end == d("2026-06-30"))
    ] + [instant("shares_outstanding_cover", "2026-05-15", 965)]
    old = conditions(assess(rules.get("0.1.0"), evidence(facts=facts)))["active.quarter_repurchase"]
    assert (old.status, old.detail) == (  # type: ignore[attr-defined]
        "unavailable",
        "not reported: shares outstanding on 2026-06-30",
    )
    new = conditions(assess(rules.get("0.2.0"), evidence(facts=facts)))["active.quarter_repurchase"]
    assert (new.status, new.value) == ("pass", Decimal("0.62"))  # type: ignore[attr-defined]  # 120 / (20 x 965)
    cap = next(i for i in new.inputs if i.name == "market_cap")  # type: ignore[attr-defined]
    assert cap.note == "close 2026-06-30 $20 x 965 shares outstanding (cover page, 2026-05-15)"


def test_a_mega_cap_passes_the_quarter_test_on_any_repurchase(rules: RulesFile) -> None:
    # B13 and B14: a market cap of $960 billion at the quarter end (960 shares at $1 billion).
    mega = [close("2026-06-30", "1000000000"), close("2026-08-14", "1000000000")]
    old = assess(rules.get("0.1.0"), evidence(closes=mega))
    assert conditions(old)["active.quarter_repurchase"].status == "fail"  # type: ignore[attr-defined]
    assert old.state == "watch"
    new = assess(rules.get("0.2.0"), evidence(closes=mega))
    quarter = conditions(new)["active.quarter_repurchase"]
    assert (quarter.status, quarter.threshold, quarter.comparison) == (  # type: ignore[attr-defined]
        "pass",
        Decimal(0),
        "above",
    )
    assert quarter.detail.startswith("mega cap (market cap at the quarter end >= $500 billion)")  # type: ignore[attr-defined]
    assert new.state == "active"
    intensity = next(c for c in new.score.components if c.component == "intensity")
    assert intensity.full == Decimal(2)
    assert intensity.detail == "mega cap (market cap >= $500 billion): 100 at 2"
    # Without repurchases a mega cap still fails.
    none = assess(rules.get("0.2.0"), evidence(facts=company(q2_2026_buyback=0), closes=mega))
    assert conditions(none)["active.quarter_repurchase"].status == "fail"  # type: ignore[attr-defined]
    # Below the mega-cap line nothing changes: the company of the other tests.
    small = next(
        c
        for c in assess(rules.get("0.2.0"), evidence()).score.components
        if c.component == "intensity"
    )
    assert small.full == Decimal(4)
