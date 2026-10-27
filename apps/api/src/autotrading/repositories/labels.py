"""Display names of the universe (M3.0c, ADR-038): config/instrument_labels.yaml, with each
symbol's GICS sector from the risk rules, or for a Taiwan code its TWSE industry from the file
(M3.7, ADR-039). For display only; nothing computes with them."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from autotrading.settings import get_settings


class _Label(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    zh: str
    about_zh: str
    sector: str | None = None  # a Taiwan code's TWSE industry (US sectors: the risk rules)


class LabelsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    sectors: dict[str, str]
    instruments: dict[str, _Label]


@dataclass(frozen=True)
class Label:
    symbol: str
    name: str
    zh: str
    about_zh: str
    sector: str | None  # the GICS key, e.g. energy
    sector_zh: str | None

    def short(self) -> str:
        """'XOM 埃克森美孚（Exxon Mobil，能源）'."""
        tail = f"{self.name}，{self.sector_zh}" if self.sector_zh else self.name
        return f"{self.symbol} {self.zh}（{tail}）"


def load_labels(path: Path | None = None) -> LabelsFile:
    path = path or get_settings().resolved_config_dir() / "instrument_labels.yaml"
    return LabelsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def _file() -> LabelsFile:
    return load_labels()


def label(symbol: str, sectors: dict[str, str] | None = None) -> Label:
    """The display label of a symbol; the ticker itself when it is not listed. `sectors` maps
    symbols to GICS keys (the risk rules' table)."""
    file = _file()
    found = file.instruments.get(symbol)
    sector = (sectors or {}).get(symbol) or (found.sector if found else None)
    sector_zh = file.sectors.get(sector) if sector else None
    if found is None:
        return Label(symbol, symbol, symbol, "", sector, sector_zh)
    return Label(symbol, found.name, found.zh, found.about_zh, sector, sector_zh)
