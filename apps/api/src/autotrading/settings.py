"""Runtime settings loaded from environment variables and the repo-root `.env`.

Secrets are typed as SecretStr so they never appear in reprs or logs.
Never log or print a Settings instance's secret values (CLAUDE.md, ADR-008).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_env_file(start: Path | None = None) -> Path | None:
    """Return the repo-root `.env` path, located by walking up to `.env.example`.

    Anchoring on the repo root makes host runs behave the same from any working
    directory. Inside containers there is no `.env.example`, so this returns None
    and configuration comes from the environment set by docker compose.
    """
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / ".env.example").is_file():
            return parent / ".env"
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "ci"] = "local"
    display_tz: str = "Asia/Singapore"

    database_url: SecretStr = SecretStr("postgresql+psycopg://app:app@localhost:5432/autotrading")
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: SecretStr = SecretStr("minioadmin")
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "raw-payloads"

    # Repo config (universe.yaml, sources.yaml). Containers mount it at /app/config.
    config_dir: Path | None = None
    # Glossary registry seed. Containers mount docs/glossary at /app/glossary.
    glossary_path: Path | None = None

    # Ingestion retries (Dramatiq, exponential backoff); after the last one -> dead letter.
    ingestion_max_retries: int = 5
    ingestion_min_backoff_ms: int = 15_000
    ingestion_max_backoff_ms: int = 600_000

    live_trading_enabled: bool = False

    def resolved_config_dir(self) -> Path:
        if self.config_dir is not None:
            return self.config_dir
        env_file = find_env_file()
        if env_file is None:
            raise RuntimeError("CONFIG_DIR is not set and no repo root was found")
        return env_file.parent / "config"

    def resolved_glossary_path(self) -> Path:
        if self.glossary_path is not None:
            return self.glossary_path
        env_file = find_env_file()
        if env_file is None:
            raise RuntimeError("GLOSSARY_PATH is not set and no repo root was found")
        return env_file.parent / "docs" / "glossary" / "glossary_seed.yaml"

    @field_validator("live_trading_enabled")
    @classmethod
    def refuse_live_trading(cls, value: bool) -> bool:
        # ADR-008: live trading stays off until Phase 6 gates are recorded as passed.
        # No such record exists yet, so any process loading settings refuses to start.
        if value:
            raise ValueError(
                "LIVE_TRADING_ENABLED=true is refused: Phase 6 gates are not recorded "
                "as passed (ADR-008). Set it to false."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
