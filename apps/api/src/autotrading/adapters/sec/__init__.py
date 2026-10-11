"""SEC EDGAR adapter (M0.5, M1.1, M1.4a, M1.5): importing it registers the `sec.tickers`,
`sec.company`, `sec.filing_xbrl`, `sec.eight_k` and `sec.earnings_release` jobs."""

from autotrading.adapters.sec import company, earnings, eight_k, filing_xbrl, tickers

__all__ = ["company", "earnings", "eight_k", "filing_xbrl", "tickers"]
