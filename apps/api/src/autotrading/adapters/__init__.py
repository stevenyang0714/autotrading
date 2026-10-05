"""Provider adapters (SEC, FRED, market data, news). Importing this package registers every
adapter's ingestion jobs with the runner's job registry."""

from autotrading.adapters import sec

__all__ = ["sec"]
