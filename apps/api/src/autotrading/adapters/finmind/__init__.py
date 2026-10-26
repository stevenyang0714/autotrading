"""FinMind adapter (M3.7b, ADR-040): importing it registers the `finmind.flows` and
`finmind.history` jobs."""

from autotrading.adapters.finmind import daily, history

__all__ = ["daily", "history"]
