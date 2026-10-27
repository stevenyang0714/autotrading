"""Provider adapters (SEC, FRED, market data, news, TWSE, FinMind). Importing this package
registers every adapter's ingestion jobs with the runner's job registry."""

from autotrading.adapters import alpaca, finmind, fred, news, sec, twse

__all__ = ["alpaca", "finmind", "fred", "news", "sec", "twse"]
