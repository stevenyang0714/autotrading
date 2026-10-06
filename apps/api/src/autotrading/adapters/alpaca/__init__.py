"""Alpaca Market Data adapter (M0.7): importing it registers `alpaca.snapshots` and
`alpaca.daily_bars`. Market data API only; no trading endpoint exists in this package."""

from autotrading.adapters.alpaca import bars, snapshots

__all__ = ["bars", "snapshots"]
