"""No code path can send an order (M1.6 acceptance 2, ADR-008): the only broker host in the
source is Alpaca's market-data host, the client reaches market-data paths only, and live trading
cannot be switched on (tests/unit/test_settings.py)."""

import re
from pathlib import Path

from autotrading.adapters.alpaca.client import ALLOWED_PATHS, DATA_HOST

SOURCE = Path(__file__).resolve().parents[2] / "src" / "autotrading"
TRADING = re.compile(
    r"api\.alpaca\.markets|paper-api|/v2/orders|/v2/positions|/v2/account|"
    r"submit_order|place_order|cancel_order"
)


def test_the_source_names_no_trading_endpoint() -> None:
    hits = [
        f"{path.relative_to(SOURCE)}:{n}"
        for path in SOURCE.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if TRADING.search(line)
    ]
    assert hits == []


def test_the_alpaca_client_reaches_market_data_only() -> None:
    assert DATA_HOST == "data.alpaca.markets"
    assert ALLOWED_PATHS == ("/v2/stocks/", "/v1/corporate-actions")
