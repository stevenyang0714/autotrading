"""Steven's investment policy against his holdings (M3.12, ADR-043): the policy's checks, drift,
the trigger and the trades that would restore the targets, on a made-up ledger."""

from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from autotrading.domain.holdings import WEIGHT, Entry, Fx, Kind, Mark, Valuation, value
from autotrading.domain.investment_policy import (
    MAX_SLEEVES,
    REBALANCING_VERSION,
    Policy,
    PolicyContent,
    Quote,
    assess,
)

SPY, TSMC, VOO, ETF50 = uuid4(), uuid4(), uuid4(), uuid4()
SYMBOLS = {SPY: "SPY", TSMC: "2330"}
RECORDED = datetime(2026, 11, 2, 3, 0, tzinfo=UTC)
T = datetime(2026, 11, 7, 3, 12, tzinfo=UTC)
DAY = date(2026, 11, 2)
TWD = Fx(Decimal("32"), date(2026, 11, 4), datetime(2026, 11, 5, 21, 0, tzinfo=UTC), "fx")
PUBLISHED = datetime(2026, 11, 6, 21, 0, tzinfo=UTC)
MARKS = {
    SPY: Mark(Decimal("610"), date(2026, 11, 6), PUBLISHED, "spy"),
    TSMC: Mark(Decimal("1500"), date(2026, 11, 6), PUBLISHED, "tsmc"),
}


def entry(kind: Kind, currency: str, *, instrument_id: UUID | None = None, **kw: str) -> Entry:
    market = None if instrument_id is None else ("US" if currency == "USD" else "TW")
    return Entry(
        id=uuid4(),
        kind=kind,
        account="Firstrade" if currency == "USD" else "元大",
        market=market,  # type: ignore[arg-type]
        instrument_id=instrument_id,
        symbol=SYMBOLS.get(instrument_id) if instrument_id else None,
        currency=currency,
        trade_date=DAY,
        quantity=Decimal(kw["quantity"]) if "quantity" in kw else None,
        price=Decimal(kw["price"]) if "price" in kw else None,
        amount=Decimal(kw["amount"]) if "amount" in kw else None,
        fee=None,
        recorded_at=RECORDED,
    )


# USD 10,000 in, 10 SPY at 600; NT$320,000 in, 100 2330 at 1,200. At T: SPY 6,100, 2330
# NT$150,000 (4,687.50), USD cash 4,000, TWD cash NT$200,000 (6,250): 21,037.50 in all
LEDGER = [
    entry("deposit", "USD", amount="10000"),
    entry("buy", "USD", instrument_id=SPY, quantity="10", price="600"),
    entry("deposit", "TWD", amount="320000"),
    entry("buy", "TWD", instrument_id=TSMC, quantity="100", price="1200"),
]
EQUITY = Fraction("21037.50")


def valuation(entries: list[Entry] = LEDGER, fx: Fx | None = TWD) -> Valuation:
    return value(entries, MARKS, {}, fx, T, T)


def sleeve(
    name: str,
    asset_class: str,
    market: str,
    target: str,
    band: str,
    *keys: str,
    targets: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "asset_class": asset_class,
        "market": market,
        "target_pct": target,
        "band_pp": band,
        "members": [
            {"key": k, **({"target_pct": targets[k]} if targets and k in targets else {})}
            for k in keys
        ],
    }


def content(*sleeves: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "goals": "Retirement in 20 years",
        "horizon_years": 20,
        "risk": "A 30% fall is tolerable",
        "sleeves": list(sleeves),
        **extra,
    }


BASE = content(
    sleeve("US equity", "equity", "US", "40", "5", "US:SPY"),
    sleeve("TW equity", "equity", "TW", "30", "5", "TW:2330", "TW:0050"),
    sleeve("Cash", "cash", "cash", "30", "10", "USD", "TWD"),
)


def policy(raw: dict[str, Any] = BASE) -> Policy:
    return Policy(1, PolicyContent.model_validate(raw), "first version", RECORDED)


def ratio(value: Fraction) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(WEIGHT)


def share(amount: str) -> Decimal:
    """`amount` USD as a share of the total."""
    return ratio(Fraction(amount) / EQUITY)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (content(sleeve("A", "equity", "US", "90", "5", "US:SPY")), "add up to 90"),
        (
            content(
                sleeve("A", "equity", "US", "50", "5", "US:SPY"),
                sleeve("B", "equity", "mixed", "50", "5", "US:SPY"),
            ),
            "more than one sleeve: US:SPY",
        ),
        (content(sleeve("Cash", "cash", "cash", "100", "5", "US:SPY")), "holds currencies"),
        (content(sleeve("A", "equity", "US", "100", "5", "TW:2330")), "not a US listing"),
        (content(sleeve("A", "cash", "US", "100", "5", "USD")), "asset class cash"),
        (content(sleeve("A", "equity", "US", "100", "5", "USD")), "holds currencies"),
        (
            content(
                sleeve(
                    "A", "equity", "US", "100", "5", "US:SPY", "US:VOO", targets={"US:SPY": "60"}
                )
            ),
            "every member a target, or none",
        ),
        (
            content(
                sleeve(
                    "A",
                    "equity",
                    "US",
                    "100",
                    "5",
                    "US:SPY",
                    "US:VOO",
                    targets={"US:SPY": "60", "US:VOO": "30"},
                )
            ),
            "add up to 90",
        ),
        (
            content(sleeve("Cash", "cash", "cash", "100", "5", "USD", targets={"USD": "100"})),
            "no target of its own",
        ),
        (
            content(
                sleeve("A", "equity", "US", "50", "5", "US:SPY"),
                sleeve("a", "equity", "TW", "50", "5", "TW:2330"),
            ),
            "share a name",
        ),
        (content(sleeve("A", "equity", "US", "100", "5")), "at least 1 item"),
        (content(sleeve("A", "equity", "US", "100", "60", "US:SPY")), "less than or equal"),
        (content(sleeve("A", "equity", "US", "50.001", "5", "US:SPY")), "decimal places"),
        (content(sleeve("A", "equity", "US", "100", "5", "US:spy")), "pattern"),
        (content(sleeve("A", "equity", "US", "100", "5", "US:SPY"), order="buy"), "Extra inputs"),
    ],
)
def test_a_policy_that_does_not_fit_is_refused(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        PolicyContent.model_validate(raw)


def test_the_policy_is_hashed_as_written_and_the_parameters_are_pinned() -> None:
    reordered = PolicyContent.model_validate(dict(reversed(list(BASE.items()))))
    assert reordered.content_sha256() == policy().content.content_sha256()
    assert REBALANCING_VERSION == "0.1.0" and MAX_SLEEVES == 12
    with pytest.raises(ValidationError, match="at most 12"):
        PolicyContent.model_validate(
            content(*[sleeve(f"S{i}", "equity", "US", "7.69", "5", f"US:A{i}") for i in range(13)])
        )


def test_drift_is_the_weight_less_the_target_and_the_groups_add_up() -> None:
    a = assess(valuation(), policy(), {})
    assert a.version == REBALANCING_VERSION and a.equity_usd == Decimal("21037.50")
    weights = {h.key: h.weight for h in a.holdings}
    assert weights == {
        "TW:2330": share("4687.50"),
        "US:SPY": share("6100"),
        "TWD": share("6250"),
        "USD": share("4000"),
    }
    drift = {s.name: (s.target, s.actual, s.drift, s.outside) for s in a.sleeves}
    us_drift = ratio(Fraction(6100) / EQUITY - Fraction(2, 5))
    assert drift["US equity"] == (Decimal("0.4"), share("6100"), us_drift, True)
    assert drift["TW equity"][1] == share("4687.50") and drift["TW equity"][3] is True
    assert drift["Cash"][1] == share("10250") and drift["Cash"][3] is True
    classes = {g.group: (g.target, g.actual) for g in a.asset_classes}
    assert classes == {
        "equity": (Decimal("0.7"), share("10787.50")),
        "cash": (Decimal("0.3"), share("10250")),
    }
    assert [(g.group, g.target) for g in a.markets] == [
        ("US", Decimal("0.4")),
        ("TW", Decimal("0.3")),
        ("cash", Decimal("0.3")),
    ]
    assert all(h.sleeve is not None for h in a.holdings) and not a.blocked


def test_a_sleeve_outside_its_band_brings_every_sleeve_to_its_target() -> None:
    """SPY to 40% of 21,037.50 (8,415: +2,315 = 3 shares at 610); 2330 to 30% (6,311.25:
    +1,623.75 = NT$51,960 = 34 shares at 1,500); 0050 holds nothing and its share of the
    sleeve is nothing; the cash sleeve is what is left."""
    a = assess(valuation(), policy(), {})
    assert a.due
    trades = {t.key: (t.side, t.amount_usd, t.shares, t.amount, t.currency) for t in a.trades}
    assert trades == {
        "US:SPY": ("buy", Decimal("2315.00"), Decimal(3), Decimal("1830.00"), "USD"),
        "TW:2330": ("buy", Decimal("1623.75"), Decimal(34), Decimal("51000.00"), "TWD"),
    }
    assert {t.key: t.weight_target for t in a.trades} == {
        "US:SPY": Decimal("0.4"),
        "TW:2330": Decimal("0.3"),
    }
    flows = {f.currency: (f.balance, f.flow, f.after) for f in a.cash_flows}
    assert flows == {
        "TWD": (Decimal("200000.00"), Decimal("-51000.00"), Decimal("149000.00")),
        "USD": (Decimal("4000.00"), Decimal("-1830.00"), Decimal("2170.00")),
    }
    after = {s.name: s.after for s in a.sleeves}
    assert after == {
        "US equity": share("7930"),
        "TW equity": share("6281.25"),
        "Cash": share("6826.25"),
    }
    assert sum((w or Decimal(0) for w in after.values()), Decimal(0)) == Decimal(1)


def test_within_the_bands_nothing_is_traded() -> None:
    wide = content(
        sleeve("US equity", "equity", "US", "40", "15", "US:SPY"),
        sleeve("TW equity", "equity", "TW", "30", "10", "TW:2330"),
        sleeve("Cash", "cash", "cash", "30", "20", "USD", "TWD"),
    )
    a = assess(valuation(), policy(wide), {})
    assert not a.due and not a.trades and not a.cash_flows
    assert all(not s.outside and s.after is None for s in a.sleeves)


def test_members_go_to_their_own_targets_or_in_equal_parts() -> None:
    """VOO (not held, 500) to 10%: 2,103.75 = 4 shares; SPY to 30% is +211.25, under one share,
    so no trade. The TW ETF sleeve holds nothing: 0050 and 006208 take 5% each; 006208 has no
    close in the database."""
    raw = content(
        sleeve(
            "US equity",
            "equity",
            "US",
            "40",
            "5",
            "US:SPY",
            "US:VOO",
            targets={"US:SPY": "30", "US:VOO": "10"},
        ),
        sleeve("TW equity", "equity", "TW", "20", "5", "TW:2330"),
        sleeve("TW ETF", "equity", "TW", "10", "5", "TW:0050", "TW:006208"),
        sleeve("Cash", "cash", "cash", "30", "10", "USD", "TWD"),
    )
    quotes = {
        "US:VOO": Quote(VOO, Mark(Decimal("500"), date(2026, 11, 6), PUBLISHED, "voo")),
        "TW:0050": Quote(ETF50, Mark(Decimal("200"), date(2026, 11, 6), PUBLISHED, "0050")),
    }
    a = assess(valuation(), policy(raw), quotes)
    trades = {t.key: (t.side, t.shares, t.instrument_id, t.flags) for t in a.trades}
    assert "US:SPY" not in trades
    assert trades["US:VOO"] == ("buy", Decimal(4), VOO, ())
    # 5% of 21,037.50 = 1,051.875 = NT$33,660 = 168 shares at 200
    assert trades["TW:0050"] == ("buy", Decimal(168), ETF50, ())
    assert trades["TW:006208"] == ("buy", None, None, ("no_close",))
    assert next(t for t in a.trades if t.key == "TW:006208").amount_usd == Decimal("1051.88")
    # 2330 to 20% (4,207.50) is a sale of 480 USD = NT$15,360 = 10 shares
    assert trades["TW:2330"][:2] == ("sell", Decimal(10))


def test_no_trade_without_a_policy_a_total_or_while_anything_is_unassigned() -> None:
    bare = assess(valuation(), None, {})
    assert bare.blocked == ("no_policy",) and not bare.sleeves and not bare.trades
    assert {h.key for h in bare.holdings} == {"US:SPY", "TW:2330", "USD", "TWD"}
    partial = content(
        sleeve("US equity", "equity", "US", "70", "5", "US:SPY"),
        sleeve("Cash", "cash", "cash", "30", "10", "USD", "TWD"),
    )
    unassigned = assess(valuation(), policy(partial), {})
    assert unassigned.blocked == ("unassigned",) and unassigned.due and not unassigned.trades
    assert next(h for h in unassigned.holdings if h.key == "TW:2330").sleeve is None
    no_rate = assess(valuation(fx=None), policy(), {})
    assert no_rate.blocked == ("no_rate",) and not no_rate.due
    assert all(h.weight is None for h in no_rate.holdings if h.currency == "TWD")
    assert all(s.actual is None and s.drift is None for s in no_rate.sleeves)
    empty = assess(valuation([]), policy(), {})
    assert empty.blocked == ("no_holdings",) and not empty.holdings and not empty.trades


def test_a_position_above_the_cap_is_flagged_never_traded_for_it() -> None:
    capped = content(
        sleeve("US equity", "equity", "US", "40", "15", "US:SPY"),
        sleeve("TW equity", "equity", "TW", "30", "10", "TW:2330"),
        sleeve("Cash", "cash", "cash", "30", "20", "USD", "TWD"),
        position_cap_pct="25",
    )
    a = assess(valuation(), policy(capped), {})
    assert {h.key for h in a.holdings if h.over_cap} == {"US:SPY"}  # 29.0%; cash is never capped
    assert not a.due and not a.trades


def test_a_trade_at_an_old_close_is_flagged() -> None:
    published = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)  # 17 days before T
    old = {**MARKS, TSMC: Mark(Decimal("1500"), date(2026, 10, 20), published, "old")}
    a = assess(value(LEDGER, old, {}, TWD, T, T), policy(), {})
    assert next(t for t in a.trades if t.key == "TW:2330").flags == ("stale_mark",)
