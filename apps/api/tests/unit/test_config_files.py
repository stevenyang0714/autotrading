"""Repo config files are valid and agree with the glossary (M0.3 plan D1)."""

import re
from pathlib import Path

import yaml

from autotrading.config_sync import load_sources
from autotrading.db.mixins import LICENSE_STATUSES
from autotrading.settings import Settings

CONFIG_DIR = Settings(_env_file=None).resolved_config_dir()  # type: ignore[call-arg]
GLOSSARY = CONFIG_DIR.parent / "docs" / "glossary" / "glossary_seed.yaml"


def glossary_enum(term_id: str) -> tuple[str, ...]:
    terms = yaml.safe_load(GLOSSARY.read_text(encoding="utf-8"))["terms"]
    formula = next(t["formula"] for t in terms if t["term_id"] == term_id)
    match = re.fullmatch(r"enum: (.+)", formula)
    assert match, formula
    return tuple(value.strip() for value in match.group(1).split("|"))


def test_license_values_match_the_glossary() -> None:
    assert glossary_enum("license_status") == LICENSE_STATUSES


def test_sources_file_is_valid() -> None:
    sources = load_sources(CONFIG_DIR / "sources.yaml").sources
    assert {s.id for s in sources} >= {"sec_edgar", "fred", "alpaca_iex", "massive", "gdelt"}


def test_sec_rate_limit_stays_well_under_ten_per_second() -> None:
    # Errata E8.
    sec = next(s for s in load_sources(CONFIG_DIR / "sources.yaml").sources if s.id == "sec_edgar")
    assert sec.rate_limit_per_second <= 5


def test_paid_massive_feed_stays_disabled_until_license_check() -> None:
    # ADR-004: activate only after the license check is recorded.
    massive = next(
        s for s in load_sources(CONFIG_DIR / "sources.yaml").sources if s.id == "massive"
    )
    assert massive.enabled is False


def test_watchlists_file_parses() -> None:
    data = yaml.safe_load((CONFIG_DIR / "watchlists.yaml").read_text(encoding="utf-8"))
    assert [a["handle"] for a in data["x_accounts"]] == ["aleabitoreddit"]


def test_config_dir_exists() -> None:
    assert isinstance(CONFIG_DIR, Path) and CONFIG_DIR.is_dir()
