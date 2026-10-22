"""Markets (M3.7, ADR-039 TW3): each instrument's market from its exchange, the Taiwan
universe file, and per-market factor definition sets."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError

from autotrading.domain.factors import Dividend, FactorDefinitionsFile, Series, price_measures
from autotrading.domain.markets import MARKETS, market_of, market_of_code
from autotrading.domain.provenance import end_of_day
from autotrading.domain.splits import Split, effective_at
from autotrading.domain.valuation import Close, close_basis
from autotrading.repositories.universe import taiwan_universe, universe_symbols
from autotrading.settings import get_settings

CONFIG = Path(get_settings().resolved_config_dir())
TAIPEI = ZoneInfo("Asia/Taipei")
FILE = FactorDefinitionsFile.model_validate(
    yaml.safe_load((CONFIG / "factor_definitions.yaml").read_text())
)
# A released version never changes (ADR-030): 0.1.0 keeps its hash with the M3.7 fields.
PINNED = {
    "0.1.0": "c6c48b837f99adfe052cc8dd85cc7a5db58aa58bfd6496d401525655e53b0605",
    "0.2.0": "5a75798b5dc31bb74d7cc5d4149bb1c7062ed42a446ec061ec488a6d5fe744f9",
}


def test_an_instrument_market_comes_from_its_exchange_or_its_code() -> None:
    assert market_of("XTAI") == "TW"
    assert market_of("XNAS") == market_of("XNYS") == market_of(None) == "US"
    assert [market_of_code(c) for c in ("2330", "0050", "00400A")] == ["TW", "TW", "TW"]
    assert [market_of_code(s) for s in ("AAPL", "BRK.B", "SPY")] == ["US", "US", "US"]
    assert MARKETS["TW"].currency == "TWD" and MARKETS["TW"].namespace == "twse"


def test_the_taiwan_universe_is_ten_companies_and_0050_quoted() -> None:
    found = taiwan_universe(CONFIG)
    assert len(found.equities) == 10 and found.etfs == ("0050",)
    assert found.benchmark == "0050" and found.ranked_on == "2026-10-21"
    assert universe_symbols("TW", CONFIG)[0] == "2330"
    assert "2330" not in universe_symbols("US", CONFIG)  # the US universe is untouched


def test_an_unquoted_code_is_refused(tmp_path: Path) -> None:
    text = (CONFIG / "universe_tw.yaml").read_text().replace('etfs: ["0050"]', "etfs: [0050]")
    (tmp_path / "universe_tw.yaml").write_text(text)
    with pytest.raises(ValueError, match="quoted TWSE code"):
        taiwan_universe(tmp_path)


def test_each_market_has_one_active_definition_set_and_released_ones_are_pinned() -> None:
    us, tw = FILE.active("US"), FILE.active("TW")
    assert (us.definition_version, us.benchmark, us.market) == ("0.1.0", "SPY", "US")
    assert (tw.definition_version, tw.benchmark, tw.market) == ("0.2.0", "0050", "TW")
    assert FILE.active() == us  # the default: the S3 and S4 rules pin 0.1.0
    assert {d.definition_version: d.content_sha256() for d in FILE.definition_sets} == PINNED
    assert tw.fundamentals.value == [] and tw.percentile_min_observations == 12
    assert tw.stale_after_days > (date(2026, 2, 23) - date(2026, 2, 11)).days  # Lunar New Year


def test_two_active_sets_in_one_market_are_refused() -> None:
    data = yaml.safe_load((CONFIG / "factor_definitions.yaml").read_text())
    data["definition_sets"][1]["market"] = "US"
    with pytest.raises(ValidationError, match="exactly one US definition set"):
        FactorDefinitionsFile.model_validate(data)


def test_a_taiwan_ex_date_and_close_are_on_taipei_dates() -> None:
    day = date(2026, 10, 21)
    # the start of a Taipei day is 16:00 UTC the day before; New York's is 04:00 UTC
    assert effective_at(day, TAIPEI) == datetime(2026, 10, 20, 16, 0, tzinfo=UTC)
    assert Split(day, Decimal(1), Decimal(2), TAIPEI).effective_at == effective_at(day, TAIPEI)
    assert Dividend(day, Decimal(5), False, TAIPEI).published_at == effective_at(day, TAIPEI)
    close = Close(day, Decimal(2420), "end_of_day", end_of_day(day, "Asia/Taipei"), TAIPEI)
    assert close_basis(close) == datetime(2026, 10, 21, 23, 59, 59, tzinfo=TAIPEI)


def test_the_taiwan_stale_check_reads_the_taipei_date() -> None:
    tw = FILE.active("TW")
    last = date(2026, 2, 11)
    closes = [Close(last, Decimal(100), "end_of_day", end_of_day(last, "Asia/Taipei"), TAIPEI)]
    series = Series("2330", closes, [], [])
    # 15 Taipei days after the last close, but still 14 in New York
    at = datetime(2026, 2, 26, 7, 0, tzinfo=TAIPEI)
    measures, found = price_measures(tw, at, series, None)
    assert found is not None and found.day == last
    assert all(m.reason == "unavailable" and "older than 14 days" in m.detail for m in measures)
    earlier = datetime(2026, 2, 25, 7, 0, tzinfo=TAIPEI)
    assert not any("older than" in m.detail for m in price_measures(tw, earlier, series, None)[0])
