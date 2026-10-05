from pathlib import Path

import pytest
from pydantic import ValidationError

from autotrading.settings import Settings, find_env_file


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_load_without_env_file() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "local"
    assert settings.display_tz == "Asia/Singapore"
    assert settings.live_trading_enabled is False


def test_secrets_are_masked_in_repr() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    text = repr(settings)
    assert "app:app" not in text
    assert "minioadmin" not in text


def test_live_trading_enabled_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    with pytest.raises(ValidationError, match="ADR-008"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_live_trading_false_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    assert Settings(_env_file=None).live_trading_enabled is False  # type: ignore[call-arg]


def test_env_file_is_anchored_to_repo_root(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("APP_ENV=local\n")
    module = tmp_path / "apps" / "api" / "src" / "autotrading" / "settings.py"
    module.parent.mkdir(parents=True)
    module.touch()
    assert find_env_file(module) == tmp_path / ".env"


def test_no_env_file_outside_repo(tmp_path: Path) -> None:
    module = tmp_path / "app" / "src" / "autotrading" / "settings.py"
    module.parent.mkdir(parents=True)
    module.touch()
    assert find_env_file(module) is None
