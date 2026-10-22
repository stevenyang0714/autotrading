"""Provider adapters (SEC, FRED, market data, news, TWSE). Importing this package registers every
adapter's ingestion jobs with the runner's job registry."""

from autotrading.adapters import alpaca, fred, news, sec, twse

__all__ = ["alpaca", "fred", "news", "sec", "twse"]
