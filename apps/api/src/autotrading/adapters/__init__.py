"""Provider adapters (SEC, FRED, market data, news). Importing this package registers every
adapter's ingestion jobs with the runner's job registry."""

from autotrading.adapters import fred, sec

__all__ = ["fred", "sec"]
