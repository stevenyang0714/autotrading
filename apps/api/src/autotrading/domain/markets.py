"""The markets the platform reads (M3.7, ADR-039 TW3). Pure.

Each instrument belongs to one market, by its primary exchange: the Taiwan Stock Exchange
(XTAI) or, for every other instrument, the US. A market fixes the time zone of its dates
(a session date, the end of its day, a split's ex-date), its currency, its session calendar,
the identifier namespace of its tickers and its universe file. A Taiwan session never borrows a
New York date, close or calendar.
"""

from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo

Market = Literal["US", "TW"]


@dataclass(frozen=True)
class MarketSpec:
    market: Market
    zone: ZoneInfo
    currency: str
    exchange: str  # ISO 10383 MIC of its session calendar
    calendar_file: str  # under config/
    namespace: str  # identifier namespace of its tickers
    universe_file: str  # under config/


US = MarketSpec(
    market="US",
    zone=ZoneInfo("America/New_York"),
    currency="USD",
    exchange="XNYS",
    calendar_file="market_calendar.yaml",
    namespace="alpaca",
    universe_file="universe.yaml",
)
TW = MarketSpec(
    market="TW",
    zone=ZoneInfo("Asia/Taipei"),
    currency="TWD",
    exchange="XTAI",
    calendar_file="market_calendar_xtai.yaml",
    namespace="twse",
    universe_file="universe_tw.yaml",
)
MARKETS: dict[Market, MarketSpec] = {"US": US, "TW": TW}
BY_EXCHANGE: dict[str, MarketSpec] = {m.exchange: m for m in MARKETS.values()}


def market_of(primary_exchange: str | None) -> Market:
    """The market of an instrument from its primary exchange: TW for XTAI, otherwise US."""
    return "TW" if primary_exchange == TW.exchange else "US"


def market_of_code(ticker: str) -> Market:
    """The market a ticker belongs to: Taiwan codes are 4 to 6 digits, optionally followed by
    a letter (0050, 2330, 00400A); US tickers start with a letter."""
    head = ticker[:4]
    return "TW" if len(ticker) <= 6 and head.isdigit() else "US"
