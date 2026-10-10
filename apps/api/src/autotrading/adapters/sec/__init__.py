"""SEC EDGAR adapter (M0.5, M1.1, M1.4a): importing it registers the `sec.tickers`,
`sec.company`, `sec.filing_xbrl` and `sec.eight_k` jobs."""

from autotrading.adapters.sec import company, eight_k, filing_xbrl, tickers

__all__ = ["company", "eight_k", "filing_xbrl", "tickers"]
