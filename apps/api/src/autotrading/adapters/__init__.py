"""Provider adapters (SEC, FRED, market data, news). Importing this package registers every
adapter's ingestion jobs with the runner's job registry."""

from autotrading.adapters import alpaca, fred, sec

__all__ = ["alpaca", "fred", "sec"]
