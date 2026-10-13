"""Macro regime and market stress (M2.1, ADR-029; build spec 02 §15, research report 01 §14).
Pure; no I/O.

From the macro observations and closes known at a time T (each with its vintage), five
dimensions of signal family 1 (Macro Regime) and one stress state of family 10 (Tail Risk /
Regime Stress):
- growth: expanding / slowing / contracting (Sahm rule, payrolls, real GDP);
- inflation: below / near / above target or hot, with its direction (core PCE);
- policy and liquidity: easy / neutral / tight (real fed funds, NFCI, curve inversion);
- credit: calm / normal / stressed / distressed (high-yield spread, else the NFCI credit index);
- volatility: calm / normal / elevated / stressed (VIX, VIX against VIX 3-month);
- a growth x inflation quadrant (a label, not a forecast);
- nine stress flags and the stress state: normal / elevated / high / crisis.
A dimension without inputs is `unavailable`, never guessed; a flag without inputs is not
counted, and the state says how many flags it judged. Thresholds come from a versioned rule
set (config/regime_rules.yaml); none places or prepares an order.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain import indicators as ind

GROWTH, INFLATION, POLICY, CREDIT, VOLATILITY = (
    "growth",
    "inflation",
    "policy",
    "credit",
    "volatility",
)
StressState = Literal["normal", "elevated", "high", "crisis"]
STRESS_ORDER: dict[str, int] = {"normal": 0, "elevated": 1, "high": 2, "crisis": 3}
FlagStatus = Literal["on", "off", "unavailable"]
TWO = Decimal("0.01")
MONTH = timedelta(days=30)
YEAR_SESSIONS, MONTH_SESSIONS = 252, 21


# ---------- rules ----------


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GrowthRule(_Rule):
    sahm_contracting: Decimal
    sahm_slowing: Decimal
    payrolls_contracting: Decimal
    payrolls_slowing: Decimal
    gdp_contracting: Decimal
    gdp_slowing: Decimal


class InflationRule(_Rule):
    target: Decimal
    near_band: Decimal
    hot: Decimal
    direction_band: Decimal


class PolicyRule(_Rule):
    real_rate_tight: Decimal
    real_rate_easy: Decimal
    nfci_tight: Decimal
    nfci_easy: Decimal
    inversion_tight_observations: Annotated[int, Field(gt=0)]


class CreditRule(_Rule):
    hy_calm: Decimal
    hy_normal: Decimal
    hy_stressed: Decimal
    hy_jump: Decimal
    nfci_credit_calm: Decimal
    nfci_credit_normal: Decimal
    nfci_credit_stressed: Decimal


class VolatilityRule(_Rule):
    vix_calm: Decimal
    vix_normal: Decimal
    vix_elevated: Decimal
    inversion_ratio: Decimal


class StressRule(_Rule):
    nfci_flag: Decimal
    stlfsi_flag: Decimal
    drawdown_flag: Decimal
    dollar_flag: Decimal
    oil_flag: Decimal
    correlation_sessions: Annotated[int, Field(gt=2)]
    correlation_flag: Decimal
    elevated_flags: Annotated[int, Field(gt=0)]
    high_flags: Annotated[int, Field(gt=0)]
    high_vix: Decimal
    crisis_vix: Decimal
    crisis_drawdown: Decimal


class RegimeRuleSet(_Rule):
    """One released rule version: immutable, like the buyback rule sets (ADR-025 B4)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    growth: GrowthRule
    inflation: InflationRule
    policy: PolicyRule
    credit: CreditRule
    volatility: VolatilityRule
    stress: StressRule

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class RegimeRuleSetEntry(RegimeRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> RegimeRuleSet:
        return RegimeRuleSet.model_validate(self.content())


class RegimeRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[RegimeRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "RegimeRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> RegimeRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


# ---------- inputs ----------


@dataclass(frozen=True)
class Obs:
    """One macro observation as known at T: its date, value and ALFRED vintage."""

    day: date
    value: Decimal
    vintage: date


@dataclass(frozen=True)
class Bar:
    """One end-of-day close known at T."""

    day: date
    close: Decimal


# ---------- result ----------


class RegimeInput(BaseModel):
    source: str  # FRED series id, or a symbol for a close
    observation_date: date
    vintage: date | None  # None for a close
    value: Decimal


class Reading(BaseModel):
    reading_id: str
    label: str
    value: Decimal | None
    unit: str
    detail: str | None = None
    inputs: list[RegimeInput]


class Dimension(BaseModel):
    dimension: str
    state: str  # a state of the dimension, or "unavailable"
    trend: str | None = None  # inflation: rising / steady / falling
    detail: str
    readings: list[Reading]


class Flag(BaseModel):
    flag_id: str
    label: str
    status: FlagStatus
    value: Decimal | None
    threshold: str
    detail: str
    inputs: list[RegimeInput]


class Regime(BaseModel):
    """Everything a regime assessment stores: recomputing it gives the same document."""

    rule_version: str
    known_at: datetime
    dimensions: list[Dimension]
    quadrant: str | None  # None when growth or inflation is unavailable
    flags: list[Flag]
    flags_on: int
    flags_available: int
    stress: StressState | None  # None when no flag could be judged
    stress_detail: str


# ---------- helpers ----------


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def _ref(source: str, o: Obs) -> RegimeInput:
    return RegimeInput(source=source, observation_date=o.day, vintage=o.vintage, value=o.value)


def _close_ref(symbol: str, b: Bar) -> RegimeInput:
    return RegimeInput(source=symbol, observation_date=b.day, vintage=None, value=b.close)


def _points(obs: Sequence[Obs]) -> list[ind.Point]:
    return [ind.Point(o.day, o.value) for o in obs]


def _month_back(obs: Sequence[Obs], months: int) -> Obs | None:
    """The observation exactly `months` months before the latest (monthly series)."""
    if not obs:
        return None
    target = obs[-1].day
    month = target.month - 1 - months
    wanted = date(target.year + month // 12, month % 12 + 1, 1)
    return next((o for o in obs if o.day == wanted), None)


def _a_month_earlier(obs: Sequence[Obs]) -> Obs | None:
    """The latest observation at or before 30 calendar days before the latest one."""
    if not obs:
        return None
    cutoff = obs[-1].day - MONTH
    earlier = [o for o in obs if o.day <= cutoff]
    return earlier[-1] if earlier else None


def _pct_change(now: Decimal, then: Decimal) -> Decimal | None:
    return None if then == 0 else _round((now / then - 1) * 100)


def _at_least(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value >= threshold


def _below(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value < threshold


# ---------- dimensions ----------


def growth(rules: GrowthRule, s: Mapping[str, Sequence[Obs]]) -> Dimension:
    unrate, payems, gdp = s.get("UNRATE", []), s.get("PAYEMS", []), s.get("GDPC1", [])
    sahm = ind.sahm_indicator(_points(unrate))
    back = _month_back(payems, 3)
    payrolls = _round((payems[-1].value - back.value) / 3) if payems and back else None
    gdp_growth = ind.annualized_growth(_points(gdp[-2:])) if len(gdp) >= 2 else None
    readings = [
        Reading(
            reading_id="sahm",
            label="Sahm rule",
            value=sahm,
            unit="percentage points",
            inputs=[_ref("UNRATE", unrate[-1])] if unrate and sahm is not None else [],
        ),
        Reading(
            reading_id="payrolls_3m",
            label="Payrolls, 3-month average change",
            value=payrolls,
            unit="thousands",
            inputs=[_ref("PAYEMS", payems[-1]), _ref("PAYEMS", back)] if back and payems else [],
        ),
        Reading(
            reading_id="gdp_annualized",
            label="Real GDP, annualized quarterly growth",
            value=gdp_growth,
            unit="percent",
            inputs=[_ref("GDPC1", o) for o in gdp[-2:]] if gdp_growth is not None else [],
        ),
    ]
    if sahm is None and payrolls is None and gdp_growth is None:
        return Dimension(
            dimension=GROWTH, state="unavailable", detail="no input known then", readings=readings
        )
    if (
        _at_least(sahm, rules.sahm_contracting)
        or _below(payrolls, rules.payrolls_contracting)
        or _below(gdp_growth, rules.gdp_contracting)
    ):
        state, detail = "contracting", "a contraction threshold is crossed"
    elif (
        _at_least(sahm, rules.sahm_slowing)
        or _below(payrolls, rules.payrolls_slowing)
        or _below(gdp_growth, rules.gdp_slowing)
    ):
        state, detail = "slowing", "a slowing threshold is crossed"
    else:
        state, detail = "expanding", "no slowing threshold is crossed"
    return Dimension(dimension=GROWTH, state=state, detail=detail, readings=readings)


def inflation(rules: InflationRule, s: Mapping[str, Sequence[Obs]]) -> Dimension:
    core, cpi = s.get("PCEPILFE", []), s.get("CPIAUCSL", [])
    yoy = ind.yoy_percent(_points(core))
    cpi_yoy = ind.yoy_percent(_points(cpi))
    back = _month_back(core, 3)
    three_month = (
        _round(Decimal(str((float(core[-1].value / back.value) ** 4 - 1) * 100)))
        if core and back and back.value
        else None
    )
    year_ago = _month_back(core, 12)
    readings = [
        Reading(
            reading_id="core_pce_yoy",
            label="Core PCE, year on year",
            value=yoy,
            unit="percent",
            detail=f"target {rules.target}%",
            inputs=[_ref("PCEPILFE", core[-1]), _ref("PCEPILFE", year_ago)]
            if yoy is not None and year_ago
            else [],
        ),
        Reading(
            reading_id="core_pce_3m",
            label="Core PCE, 3-month annualized",
            value=three_month,
            unit="percent",
            inputs=[_ref("PCEPILFE", core[-1]), _ref("PCEPILFE", back)]
            if three_month is not None and back
            else [],
        ),
        Reading(
            reading_id="cpi_yoy",
            label="CPI, year on year",
            value=cpi_yoy,
            unit="percent",
            inputs=[_ref("CPIAUCSL", cpi[-1])] if cpi_yoy is not None else [],
        ),
    ]
    if yoy is None:
        return Dimension(
            dimension=INFLATION,
            state="unavailable",
            detail="no core PCE year on year known then",
            readings=readings,
        )
    if yoy > rules.hot:
        state = "hot"
    elif yoy > rules.target + rules.near_band:
        state = "above_target"
    elif yoy < rules.target - rules.near_band:
        state = "below_target"
    else:
        state = "near_target"
    trend = None
    if three_month is not None:
        if three_month > yoy + rules.direction_band:
            trend = "rising"
        elif three_month < yoy - rules.direction_band:
            trend = "falling"
        else:
            trend = "steady"
    detail = f"core PCE {yoy}% against the {rules.target}% target"
    return Dimension(
        dimension=INFLATION, state=state, trend=trend, detail=detail, readings=readings
    )


def policy(
    rules: PolicyRule, s: Mapping[str, Sequence[Obs]], core_yoy: Decimal | None
) -> Dimension:
    fed, nfci, curve = s.get("FEDFUNDS", []), s.get("NFCI", []), s.get("T10Y2Y", [])
    real = _round(fed[-1].value - core_yoy) if fed and core_yoy is not None else None
    nfci_value = nfci[-1].value if nfci else None
    streak = ind.inversion_streak(_points(curve))
    readings = [
        Reading(
            reading_id="real_fed_funds",
            label="Real fed funds rate",
            value=real,
            unit="percent",
            detail="fed funds minus core PCE year on year",
            inputs=[_ref("FEDFUNDS", fed[-1])] if real is not None else [],
        ),
        Reading(
            reading_id="nfci",
            label="Chicago Fed NFCI",
            value=nfci_value,
            unit="index",
            detail="above 0: tighter than average",
            inputs=[_ref("NFCI", nfci[-1])] if nfci else [],
        ),
        Reading(
            reading_id="curve_inversion",
            label="10y-2y curve, observations on the current side",
            value=Decimal(streak.observations) if streak else None,
            unit="observations",
            detail=("inverted" if streak.inverted else "positive") + f" since {streak.since}"
            if streak
            else None,
            inputs=[_ref("T10Y2Y", curve[-1])] if curve else [],
        ),
    ]
    if real is None and nfci_value is None:
        return Dimension(
            dimension=POLICY, state="unavailable", detail="no input known then", readings=readings
        )
    inverted_long = bool(
        streak and streak.inverted and streak.observations >= rules.inversion_tight_observations
    )
    if (
        (real is not None and real > rules.real_rate_tight)
        or (nfci_value is not None and nfci_value > rules.nfci_tight)
        or inverted_long
    ):
        state, detail = "tight", "a tight threshold is crossed"
    elif (real is None or real < rules.real_rate_easy) and (
        nfci_value is None or nfci_value < rules.nfci_easy
    ):
        state, detail = "easy", "the real rate and financial conditions are easy"
    else:
        state, detail = "neutral", "neither tight nor easy"
    return Dimension(dimension=POLICY, state=state, detail=detail, readings=readings)


def credit(rules: CreditRule, s: Mapping[str, Sequence[Obs]]) -> Dimension:
    hy, nfci_credit = s.get("BAMLH0A0HYM2", []), s.get("NFCICREDIT", [])
    if hy:
        level = hy[-1].value
        earlier = _a_month_earlier(hy)
        jump = _round(level - earlier.value) if earlier else None
        readings = [
            Reading(
                reading_id="hy_oas",
                label="High-yield spread",
                value=level,
                unit="percent",
                inputs=[_ref("BAMLH0A0HYM2", hy[-1])],
            ),
            Reading(
                reading_id="hy_oas_change",
                label="High-yield spread, change over a month",
                value=jump,
                unit="percentage points",
                inputs=[_ref("BAMLH0A0HYM2", earlier)] if earlier else [],
            ),
        ]
        if level >= rules.hy_stressed:
            state = "distressed"
        elif level >= rules.hy_normal or _at_least(jump, rules.hy_jump):
            state = "stressed"
        elif level >= rules.hy_calm:
            state = "normal"
        else:
            state = "calm"
        return Dimension(
            dimension=CREDIT, state=state, detail="from the high-yield spread", readings=readings
        )
    if nfci_credit:
        value = nfci_credit[-1].value
        readings = [
            Reading(
                reading_id="nfci_credit",
                label="NFCI credit subindex",
                value=value,
                unit="index",
                inputs=[_ref("NFCICREDIT", nfci_credit[-1])],
            )
        ]
        if value > rules.nfci_credit_stressed:
            state = "distressed"
        elif value > rules.nfci_credit_normal:
            state = "stressed"
        elif value > rules.nfci_credit_calm:
            state = "normal"
        else:
            state = "calm"
        return Dimension(
            dimension=CREDIT,
            state=state,
            detail="from the NFCI credit subindex (no high-yield spread known then)",
            readings=readings,
        )
    return Dimension(
        dimension=CREDIT, state="unavailable", detail="no input known then", readings=[]
    )


def volatility(rules: VolatilityRule, s: Mapping[str, Sequence[Obs]]) -> Dimension:
    vix, vix3m = s.get("VIXCLS", []), s.get("VXVCLS", [])
    ratio = _round(vix[-1].value / vix3m[-1].value) if vix and vix3m and vix3m[-1].value else None
    readings = [
        Reading(
            reading_id="vix",
            label="VIX",
            value=vix[-1].value if vix else None,
            unit="index",
            inputs=[_ref("VIXCLS", vix[-1])] if vix else [],
        ),
        Reading(
            reading_id="vix_term",
            label="VIX / VIX 3-month",
            value=ratio,
            unit="ratio",
            detail="above 1: inverted term structure",
            inputs=[_ref("VXVCLS", vix3m[-1])] if ratio is not None else [],
        ),
    ]
    if not vix:
        return Dimension(
            dimension=VOLATILITY, state="unavailable", detail="no VIX known then", readings=readings
        )
    level = vix[-1].value
    if level >= rules.vix_elevated:
        state = "stressed"
    elif level >= rules.vix_normal or (ratio is not None and ratio > rules.inversion_ratio):
        state = "elevated"
    elif level >= rules.vix_calm:
        state = "normal"
    else:
        state = "calm"
    return Dimension(dimension=VOLATILITY, state=state, detail=f"VIX {level}", readings=readings)


def quadrant(growth_state: str, inflation_state: str) -> str | None:
    if "unavailable" in (growth_state, inflation_state):
        return None
    high = inflation_state in ("above_target", "hot")
    if growth_state == "expanding":
        return "reflation" if high else "goldilocks"
    return "stagflation" if high else "disinflationary_slowdown"


# ---------- stress ----------


def _flag(
    flag_id: str,
    label: str,
    on: bool | None,
    value: Decimal | None,
    threshold: str,
    detail: str,
    inputs: list[RegimeInput],
) -> Flag:
    status: FlagStatus = "unavailable" if on is None else ("on" if on else "off")
    return Flag(
        flag_id=flag_id,
        label=label,
        status=status,
        value=value,
        threshold=threshold,
        detail=detail,
        inputs=inputs,
    )


def drawdown(bars: Sequence[Bar]) -> Decimal | None:
    """% below the highest close of the last 252 sessions (positive = below the high)."""
    window = bars[-YEAR_SESSIONS:]
    if len(window) < MONTH_SESSIONS:
        return None
    high = max(b.close for b in window)
    return _round((1 - window[-1].close / high) * 100) if high else None


def correlation(a: Sequence[Bar], b: Sequence[Bar], sessions: int) -> Decimal | None:
    """Pearson correlation of the two series' daily returns over their last common sessions."""
    closes_b = {x.day: x.close for x in b}
    common = [(x.close, closes_b[x.day]) for x in a if x.day in closes_b]
    pairs = common[-(sessions + 1) :]
    if len(pairs) < sessions + 1:
        return None
    ra = [pairs[i][0] / pairs[i - 1][0] - 1 for i in range(1, len(pairs))]
    rb = [pairs[i][1] / pairs[i - 1][1] - 1 for i in range(1, len(pairs))]
    n = Decimal(len(ra))
    ma, mb = sum(ra, Decimal(0)) / n, sum(rb, Decimal(0)) / n
    cov = sum(((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True)), Decimal(0))
    va = sum(((x - ma) ** 2 for x in ra), Decimal(0))
    vb = sum(((y - mb) ** 2 for y in rb), Decimal(0))
    if va == 0 or vb == 0:
        return None
    return _round(cov / (va.sqrt() * vb.sqrt()))


def flags(
    rules: StressRule,
    inversion_ratio: Decimal,
    s: Mapping[str, Sequence[Obs]],
    spy: Sequence[Bar],
    tlt: Sequence[Bar],
    dims: Mapping[str, Dimension],
) -> list[Flag]:
    nfci, stlfsi = s.get("NFCI", []), s.get("STLFSI4", [])
    dollar, oil = s.get("DTWEXBGS", []), s.get("DCOILWTICO", [])
    vol = dims[VOLATILITY]
    term = next((r for r in vol.readings if r.reading_id == "vix_term"), None)
    dd = drawdown(spy)
    dollar_then, oil_then = _a_month_earlier(dollar), _a_month_earlier(oil)
    dollar_change = (
        _pct_change(dollar[-1].value, dollar_then.value) if dollar and dollar_then else None
    )
    oil_change = _pct_change(oil[-1].value, oil_then.value) if oil and oil_then else None
    corr = correlation(spy, tlt, rules.correlation_sessions)
    month = spy[-(MONTH_SESSIONS + 1) :]
    spy_month = (
        _round((month[-1].close / month[0].close - 1) * 100)
        if len(month) == MONTH_SESSIONS + 1 and month[0].close
        else None
    )
    credit_state, vol_state = dims[CREDIT].state, vol.state
    spy_refs = [_close_ref("SPY", spy[-1])] if spy else []
    return [
        _flag(
            "credit_stress",
            "Credit stressed or distressed",
            None if credit_state == "unavailable" else credit_state in ("stressed", "distressed"),
            None,
            "credit state stressed or distressed",
            f"credit {credit_state}",
            [i for r in dims[CREDIT].readings for i in r.inputs],
        ),
        _flag(
            "volatility_stress",
            "Volatility elevated or stressed",
            None if vol_state == "unavailable" else vol_state in ("elevated", "stressed"),
            None,
            "volatility state elevated or stressed",
            f"volatility {vol_state}",
            [i for r in vol.readings for i in r.inputs],
        ),
        _flag(
            "nfci_tight",
            "Financial conditions tighter than average",
            nfci[-1].value > rules.nfci_flag if nfci else None,
            nfci[-1].value if nfci else None,
            f"NFCI above {rules.nfci_flag}",
            "Chicago Fed NFCI",
            [_ref("NFCI", nfci[-1])] if nfci else [],
        ),
        _flag(
            "stlfsi_high",
            "Financial stress above normal",
            stlfsi[-1].value > rules.stlfsi_flag if stlfsi else None,
            stlfsi[-1].value if stlfsi else None,
            f"St. Louis Fed stress index above {rules.stlfsi_flag}",
            "STLFSI4",
            [_ref("STLFSI4", stlfsi[-1])] if stlfsi else [],
        ),
        _flag(
            "vix_inverted",
            "VIX term structure inverted",
            None if term is None or term.value is None else term.value > inversion_ratio,
            term.value if term else None,
            f"VIX / VIX 3-month above {inversion_ratio}",
            "VIX / VIX 3-month",
            term.inputs if term else [],
        ),
        _flag(
            "equity_drawdown",
            "Stocks well below their high",
            None if dd is None else dd > rules.drawdown_flag,
            dd,
            f"SPY more than {rules.drawdown_flag}% below its 252-session high",
            "SPY drawdown",
            spy_refs,
        ),
        _flag(
            "dollar_surge",
            "Dollar surge",
            None if dollar_change is None else dollar_change > rules.dollar_flag,
            dollar_change,
            f"broad dollar up more than {rules.dollar_flag}% in a month",
            "DTWEXBGS change over a month",
            [_ref("DTWEXBGS", dollar[-1]), _ref("DTWEXBGS", dollar_then)]
            if dollar and dollar_then
            else [],
        ),
        _flag(
            "oil_shock",
            "Oil shock",
            None if oil_change is None else abs(oil_change) > rules.oil_flag,
            oil_change,
            f"WTI moves more than {rules.oil_flag}% in a month",
            "DCOILWTICO change over a month",
            [_ref("DCOILWTICO", oil[-1]), _ref("DCOILWTICO", oil_then)] if oil and oil_then else [],
        ),
        _flag(
            "stock_bond_selloff",
            "Stocks and bonds falling together",
            None
            if corr is None or spy_month is None
            else corr > rules.correlation_flag and spy_month < 0,
            corr,
            f"SPY-TLT {rules.correlation_sessions}-session correlation above "
            f"{rules.correlation_flag} while SPY fell over {MONTH_SESSIONS} sessions",
            f"SPY over {MONTH_SESSIONS} sessions: {spy_month}%" if spy_month is not None else "",
            spy_refs + ([_close_ref("TLT", tlt[-1])] if tlt else []),
        ),
    ]


def stress_state(
    rules: StressRule, found: Sequence[Flag], dims: Mapping[str, Dimension]
) -> tuple[StressState | None, str]:
    on = sum(f.status == "on" for f in found)
    available = sum(f.status != "unavailable" for f in found)
    if available == 0:
        return None, "no stress flag could be judged"
    vix = next((r.value for r in dims[VOLATILITY].readings if r.reading_id == "vix"), None)
    dd = next((f.value for f in found if f.flag_id == "equity_drawdown"), None)
    distressed = dims[CREDIT].state == "distressed"
    basis = f"{on} of {available} available flags on"
    if (
        distressed
        and vix is not None
        and vix > rules.crisis_vix
        and dd is not None
        and dd > rules.crisis_drawdown
    ):
        return "crisis", f"{basis}; credit distressed, VIX and drawdown at crisis levels"
    if on >= rules.high_flags or distressed or (vix is not None and vix > rules.high_vix):
        return "high", basis
    if on >= rules.elevated_flags:
        return "elevated", basis
    return "normal", basis


def assess(
    rules: RegimeRuleSet,
    at: datetime,
    series: Mapping[str, Sequence[Obs]],
    spy: Sequence[Bar],
    tlt: Sequence[Bar],
) -> Regime:
    """The regime as known at T from the observations and closes known then (oldest first)."""
    g = growth(rules.growth, series)
    i = inflation(rules.inflation, series)
    core_yoy = next((r.value for r in i.readings if r.reading_id == "core_pce_yoy"), None)
    dims = {
        GROWTH: g,
        INFLATION: i,
        POLICY: policy(rules.policy, series, core_yoy),
        CREDIT: credit(rules.credit, series),
        VOLATILITY: volatility(rules.volatility, series),
    }
    found = flags(rules.stress, rules.volatility.inversion_ratio, series, spy, tlt, dims)
    stress, detail = stress_state(rules.stress, found, dims)
    return Regime(
        rule_version=rules.rule_version,
        known_at=at,
        dimensions=list(dims.values()),
        quadrant=quadrant(g.state, i.state),
        flags=found,
        flags_on=sum(f.status == "on" for f in found),
        flags_available=sum(f.status != "unavailable" for f in found),
        stress=stress,
        stress_detail=detail,
    )
