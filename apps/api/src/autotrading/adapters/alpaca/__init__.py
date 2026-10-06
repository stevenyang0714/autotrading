"""Alpaca Market Data adapter (M0.7, M1.1): importing it registers `alpaca.snapshots`,
`alpaca.daily_bars` and `alpaca.splits`. Market data API only; no trading endpoint exists in
this package."""

from autotrading.adapters.alpaca import bars, snapshots, splits

__all__ = ["bars", "snapshots", "splits"]
