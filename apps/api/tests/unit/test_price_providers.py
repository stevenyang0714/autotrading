"""Price providers behind one interface (ADR-004): Alpaca active, Massive a placeholder."""

from autotrading.adapters.alpaca.provider import AlpacaProvider
from autotrading.adapters.massive.provider import MassiveProvider
from autotrading.api.prices import PRICE_PROVIDER
from autotrading.domain.prices import PriceProvider


def test_both_providers_implement_the_interface() -> None:
    providers: list[PriceProvider] = [AlpacaProvider(), MassiveProvider()]
    assert [(p.source_id, p.live_feed_status) for p in providers] == [
        ("alpaca_iex", "live_single_venue"),
        ("massive", "live_consolidated"),
    ]


def test_massive_stays_off_until_licensed() -> None:
    assert MassiveProvider().configured() is False


def test_the_api_reads_alpaca() -> None:
    assert isinstance(PRICE_PROVIDER, AlpacaProvider)
