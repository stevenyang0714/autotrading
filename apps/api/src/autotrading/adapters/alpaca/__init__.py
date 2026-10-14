"""Alpaca Market Data adapter (M0.7, M1.1, M2.2): importing it registers `alpaca.snapshots`,
`alpaca.daily_bars`, `alpaca.splits` and `alpaca.dividends`. Market data API only; no trading
endpoint exists in this package."""

from autotrading.adapters.alpaca import bars, dividends, snapshots, splits

__all__ = ["bars", "dividends", "snapshots", "splits"]
