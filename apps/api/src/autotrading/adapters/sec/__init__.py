"""SEC EDGAR adapter (M0.5, M1.1): importing it registers the `sec.tickers`, `sec.company` and
`sec.filing_xbrl` jobs."""

from autotrading.adapters.sec import company, filing_xbrl, tickers

__all__ = ["company", "filing_xbrl", "tickers"]
