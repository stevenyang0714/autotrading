"""Alpaca Market Data behind the PriceProvider interface (ADR-004, ADR-017): IEX quotes, so a
fresh quote is a single-venue price."""

from typing import ClassVar

from autotrading.adapters.alpaca.client import configured
from autotrading.adapters.alpaca.symbols import SOURCE_ID
from autotrading.domain.prices import FeedStatus


class AlpacaProvider:
    source_id: ClassVar[str] = SOURCE_ID
    live_feed_status: ClassVar[FeedStatus] = "live_single_venue"

    def configured(self) -> bool:
        return configured()
