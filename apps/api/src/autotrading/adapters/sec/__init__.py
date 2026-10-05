"""SEC EDGAR adapter (M0.5): importing it registers the `sec.tickers` and `sec.company` jobs."""

from autotrading.adapters.sec import company, tickers

__all__ = ["company", "tickers"]
