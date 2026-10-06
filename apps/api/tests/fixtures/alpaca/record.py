"""Re-record the Alpaca fixtures from the live market data API (opt-in, needs the paper
APCA_* keys in .env).

    cd apps/api && uv run python -m tests.fixtures.alpaca.record

Runs the real job fetches (adapters/alpaca), so the recorded URLs are exactly what replay
requests:
- `alpaca.snapshots` for every universe symbol (IEX). Record outside US market hours, so the
  quotes are the last session's close;
- `alpaca.daily_bars` for every universe symbol over one year, raw and split-adjusted (SIP);
- `alpaca.daily_bars` for NVDA around its 10-for-1 split on 2024-06-10. The job also fetches
  NVDA's full split-adjusted history, as it does for any symbol that split in its window.
Responses are stored unmodified. Keys travel as headers, so URLs carry none; the recorder
still checks every file and URL for them.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from autotrading.adapters.alpaca.bars import AlpacaDailyBarsJob
from autotrading.adapters.alpaca.refresh import universe
from autotrading.adapters.alpaca.snapshots import AlpacaSnapshotsJob
from autotrading.ingestion.job import FetchContext, IngestionJob, Window
from autotrading.settings import get_settings

HERE = Path(__file__).resolve().parent
NVDA_SPLIT_WINDOW = {"symbols": ["NVDA"], "etfs": [], "start": "2024-06-03", "end": "2024-06-14"}


def throttle() -> None:
    time.sleep(0.4)  # well under the 200 requests/minute of the free plan


def main() -> None:
    settings = get_settings()
    symbols, etfs = universe(settings.resolved_config_dir())
    # A date-only `end` means the end of that day; the free plan refuses SIP data from the
    # last 15 minutes, so the year ends yesterday.
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    runs: list[tuple[str, type[IngestionJob], dict[str, Any]]] = [
        ("snapshots", AlpacaSnapshotsJob, {"symbols": symbols, "etfs": etfs}),
        (
            "bars_year",
            AlpacaDailyBarsJob,
            {
                "symbols": symbols,
                "etfs": etfs,
                "start": (yesterday - timedelta(days=365)).isoformat(),
                "end": yesterday.isoformat(),
            },
        ),
        ("bars_nvda_split", AlpacaDailyBarsJob, NVDA_SPLIT_WINDOW),
    ]
    files: dict[str, str] = {}
    for label, job_class, params in runs:
        job = job_class(params, Window())
        for i, payload in enumerate(job.fetch(FetchContext(run_id=uuid4(), acquire=throttle))):
            name = f"{label}_{i:02d}.json"
            (HERE / name).write_bytes(payload.content)
            files[payload.source_url] = name

    secrets = [
        value.get_secret_value()
        for value in (settings.apca_api_key_id, settings.apca_api_secret_key)
        if value and value.get_secret_value()
    ]
    for secret in secrets:
        if any(secret in url for url in files):
            raise SystemExit("an Alpaca key is in a URL; not writing the manifest")
        for name in files.values():
            if secret in (HERE / name).read_text(encoding="utf-8"):
                raise SystemExit(f"an Alpaca key is in {name}; not writing the manifest")

    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "runs": [{"job": job_class.name, "params": params} for _, job_class, params in runs],
        "files": files,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(files)} files into {HERE}")


if __name__ == "__main__":
    main()
