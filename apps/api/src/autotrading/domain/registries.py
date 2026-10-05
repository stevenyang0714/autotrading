"""Canonical registries. IDs are immutable (CLAUDE.md non-negotiables).

Sources: signal families 02 §2; strategies 02 §18 (errata E14: §18 wording wins over §30);
source tiers 01 §20 with labels from 01 §7 (errata E2: Tier 1 = strongest).

The baseline migration seeds the same values as literals, because a migration must not import
application code. Tests assert that the database rows equal these constants.
"""

from dataclasses import dataclass
from typing import Literal

DefaultMode = Literal["paper_semi_auto", "alert_semi_auto", "alert", "alert_only"]

DEFAULT_MODE_LABELS: dict[DefaultMode, str] = {
    "paper_semi_auto": "Paper / Semi-auto",
    "alert_semi_auto": "Alert / Semi-auto",
    "alert": "Alert",
    "alert_only": "Alert only",
}


@dataclass(frozen=True)
class SignalFamily:
    id: int
    name: str


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    default_mode: DefaultMode
    unlock_condition: str


@dataclass(frozen=True)
class SourceTier:
    tier: int
    label: str
    role: str
    examples: str


SIGNAL_FAMILIES: tuple[SignalFamily, ...] = (
    SignalFamily(1, "Macro Regime"),
    SignalFamily(2, "Corporate Actions & Capital Structure"),
    SignalFamily(3, "Fundamental & Valuation"),
    SignalFamily(4, "Earnings & Estimates"),
    SignalFamily(5, "Price / Trend / Factor"),
    SignalFamily(6, "Options & Volatility"),
    SignalFamily(7, "Positioning & Flows"),
    SignalFamily(8, "Alternative / Physical / Supply Chain"),
    SignalFamily(9, "Geopolitical / Policy / Social Intelligence"),
    SignalFamily(10, "Tail Risk / Regime Stress"),
)

STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        "S1",
        "Buyback + Value + Quality",
        "paper_semi_auto",
        "OOS + walk-forward + robustness + risk",
    ),
    Strategy(
        "S2",
        "Earnings Surprise + Revisions + Momentum",
        "paper_semi_auto",
        "OOS + event timing + cost",
    ),
    Strategy("S3", "Macro Regime / ETF Rotation", "paper_semi_auto", "regime robustness"),
    Strategy("S4", "Medium-term Momentum", "paper_semi_auto", "factor overlap + OOS"),
    Strategy(
        "S5", "Event / Supply-chain", "alert_semi_auto", "causal evidence + market confirmation"
    ),
    Strategy("S6", "Options / Volatility", "alert_semi_auto", "Greeks + liquidity + max loss"),
    Strategy("S7", "Corporate Insider", "alert", "source/context validation"),
    Strategy("S8", "Congress PTR", "alert", "disclosure-lag aware"),
    Strategy("S9", "Political / Trump headlines", "alert", "official status + transmission map"),
    Strategy("S10", "Intraday social headline", "alert_only", "no social-only execution"),
    Strategy("S11", "Small-cap squeeze", "alert_only", "no default auto"),
    Strategy("S12", "0DTE speculation", "alert_only", "no default auto"),
)

SOURCE_TIERS: tuple[SourceTier, ...] = (
    SourceTier(
        1,
        "Primary / official",
        "trade-critical confirmation",
        "SEC/EDGAR; licensed market-price/venue feeds (e.g., Massive); issuer filings; "
        "FRED/ALFRED; Treasury; CFTC; White House; House/Senate disclosure; official agency data",
    ),
    SourceTier(
        2,
        "Professional media",
        "fast discovery/context; license required",
        "Reuters; FT; WSJ; Bloomberg; AP; CNBC; Economist; licensed research/data",
    ),
    SourceTier(
        3,
        "Specialist / social",
        "early signal / attention",
        "X research accounts; specialist blogs/newsletters; community",
    ),
    SourceTier(
        4,
        "Anonymous / unverified",
        "weak lead only; never sole execution evidence",
        "anonymous source; repost; unverified social",
    ),
)
