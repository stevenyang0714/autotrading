"""Massive (formerly Polygon.io), the canonical consolidated price feed (ADR-004): a placeholder
behind the PriceProvider interface. It never reports itself configured, so nothing reads or
schedules it, until a key and the license check (redistribution and personal use) are
recorded and a milestone adds the jobs.
"""

from typing import ClassVar

from autotrading.domain.prices import FeedStatus


class MassiveProvider:
    source_id: ClassVar[str] = "massive"
    # A consolidated real-time feed, once licensed; delayed on lower plans.
    live_feed_status: ClassVar[FeedStatus] = "live_consolidated"

    def configured(self) -> bool:
        return False
