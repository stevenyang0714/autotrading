"""Display names of the universe (M3.0c, ADR-038): every symbol listed, sectors labelled."""

from pathlib import Path

import yaml

from autotrading.repositories.labels import label, load_labels
from autotrading.settings import get_settings

CONFIG = Path(get_settings().resolved_config_dir())


def test_every_universe_symbol_has_a_label_and_every_sector_a_chinese_name() -> None:
    universe = yaml.safe_load((CONFIG / "universe.yaml").read_text())
    taiwan = yaml.safe_load((CONFIG / "universe_tw.yaml").read_text())
    symbols = set(universe["equities"]) | set(universe["etfs"])
    codes = set(taiwan["equities"]) | set(taiwan["etfs"])
    labels = load_labels()
    assert set(labels.instruments) == symbols | codes  # both markets (M3.7)
    risk = yaml.safe_load((CONFIG / "risk_rules.yaml").read_text())
    sectors = {e["sector"] for r in risk["rule_sets"] for e in r["sectors"].values()}
    assert sectors <= set(labels.sectors)
    # a Taiwan code carries its TWSE industry; a US symbol takes its sector from the risk rules
    assert all(labels.instruments[c].sector in labels.sectors for c in codes)
    assert all(labels.instruments[s].sector is None for s in symbols)


def test_a_label_reads_ticker_chinese_name_english_name_and_sector() -> None:
    xom = label("XOM", {"XOM": "energy"})
    assert xom.short() == "XOM 埃克森美孚（Exxon Mobil，能源）"
    assert xom.about_zh == "石油與天然氣"
    assert label("ZZZ").short() == "ZZZ ZZZ（ZZZ）"  # not listed: the ticker itself


def test_a_taiwan_label_carries_its_twse_industry() -> None:
    assert label("2330").short() == "2330 台積電（TSMC，半導體業）"
    assert label("0050").short() == "0050 元大台灣50（Yuanta Taiwan Top 50 ETF，台股大盤）"
