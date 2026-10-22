"""The universe of each market (M3.7, ADR-039 TW2): config/universe.yaml for the US and
config/universe_tw.yaml for Taiwan, in their file order."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from autotrading.domain.markets import MARKETS, Market
from autotrading.settings import get_settings

TAIWAN_CODE = re.compile(r"^\d{4}[0-9A-Z]{0,2}$")


@dataclass(frozen=True)
class TaiwanUniverse:
    equities: tuple[str, ...]
    etfs: tuple[str, ...]
    benchmark: str
    ranked_on: str

    @property
    def codes(self) -> tuple[str, ...]:
        return self.equities + self.etfs


def taiwan_universe(config_dir: Path | None = None) -> TaiwanUniverse:
    """config/universe_tw.yaml; every code must be a quoted TWSE code."""
    config_dir = config_dir or get_settings().resolved_config_dir()
    path = config_dir / MARKETS["TW"].universe_file
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    def codes(key: str) -> tuple[str, ...]:
        found = data.get(key) or []
        for code in found:
            if not isinstance(code, str) or not TAIWAN_CODE.match(code):
                raise ValueError(f"universe_tw.yaml {key}: {code!r} is not a quoted TWSE code")
        return tuple(found)

    benchmark = str(data["benchmark"])
    found = TaiwanUniverse(codes("equities"), codes("etfs"), benchmark, str(data["ranked_on"]))
    if benchmark not in found.codes:
        raise ValueError(f"universe_tw.yaml: the benchmark {benchmark} is not in the universe")
    return found


def universe_symbols(market: Market = "US", config_dir: Path | None = None) -> list[str]:
    """Every symbol of a market's universe, in file order (equities, then ETFs)."""
    config_dir = config_dir or get_settings().resolved_config_dir()
    if market == "TW":
        return list(taiwan_universe(config_dir).codes)
    # imported here: the adapters package imports the TWSE job, which imports this module
    from autotrading.adapters.alpaca.refresh import universe

    everything, _ = universe(config_dir)
    return everything
