"""TWSE OpenAPI adapter (M3.7, ADR-039): importing it registers the `twse.daily` job."""

from autotrading.adapters.twse import daily

__all__ = ["daily"]
