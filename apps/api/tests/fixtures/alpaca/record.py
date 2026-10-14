"""Re-record the Alpaca fixtures from the live market data API (opt-in, needs the paper
APCA_* keys in .env).

    cd apps/api && uv run python -m tests.fixtures.alpaca.record

Runs the real job fetches (adapters/alpaca), so the recorded URLs are exactly what replay
requests:
- `alpaca.snapshots` for every universe symbol (IEX). Record outside US market hours, so the
  quotes are the last session's close;
- `alpaca.daily_bars` for every universe symbol over one year, raw and split-adjusted (SIP);
- `alpaca.daily_bars` for NVDA around its 10-for-1 split on 2024-06-10. The job also fetches
  NVDA's full split-adjusted history, as it does for any symbol that split in its window;
- `alpaca.splits` for the universe since 2016 (M1.1; ETFs since M2.2);
- `alpaca.dividends` for the universe since 2016 (M2.2);
- `alpaca.daily_bars` for NVDA and SPY from 2023-05 to the start of the year above (M2.2), so
  a 12-month momentum across NVDA's 2024 split can be computed.
`--only splits,dividends` (labels) records just those runs and keeps the others.
Responses are stored unmodified. Keys travel as headers, so URLs carry none; the recorder
still checks every file and URL for them.
"""

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from autotrading.adapters.alpaca.bars import AlpacaDailyBarsJob
from autotrading.adapters.alpaca.dividends import AlpacaDividendsJob
from autotrading.adapters.alpaca.refresh import universe
from autotrading.adapters.alpaca.snapshots import AlpacaSnapshotsJob
from autotrading.adapters.alpaca.splits import HISTORY_START, AlpacaSplitsJob
from autotrading.ingestion.job import FetchContext, IngestionJob, Window
from autotrading.settings import get_settings

HERE = Path(__file__).resolve().parent
NVDA_SPLIT_WINDOW = {"symbols": ["NVDA"], "etfs": [], "start": "2024-06-03", "end": "2024-06-14"}
SPLITS_END = "2026-10-05"
DIVIDENDS_END = "2026-10-05"
# Two years before the recorded year (which starts 2025-10-05), for 12-month measures (M2.2).
HISTORY_WINDOW = {
    "symbols": ["NVDA", "SPY"],
    "etfs": ["SPY"],
    "start": "2023-05-01",
    "end": "2025-10-04",
}


def throttle() -> None:
    time.sleep(0.4)  # well under the 200 requests/minute of the free plan


def _label(run: dict[str, Any]) -> str:
    """The label of a run recorded before labels were stored (M2.2)."""
    if run["job"] == "alpaca.splits":
        return "splits"
    if run["job"] == "alpaca.snapshots":
        return "snapshots"
    return "bars_nvda_split" if run["params"]["symbols"] == ["NVDA"] else "bars_year"


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
        (
            "splits",
            AlpacaSplitsJob,
            {"symbols": symbols, "start": HISTORY_START, "end": SPLITS_END},
        ),
        (
            "dividends",
            AlpacaDividendsJob,
            {"symbols": symbols, "start": HISTORY_START, "end": DIVIDENDS_END},
        ),
        ("bars_history", AlpacaDailyBarsJob, HISTORY_WINDOW),
    ]
    files: dict[str, str] = {}
    previous: dict[str, Any] = {}
    only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--only=")), None)
    if only:
        labels = set(only.split(","))
        previous = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
        files = {u: n for u, n in previous["files"].items() if n.rsplit("_", 1)[0] not in labels}
        runs = [run for run in runs if run[0] in labels]
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

    recorded = [
        {"label": label, "job": job_class.name, "params": params}
        for label, job_class, params in runs
    ]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    kept = [
        r
        for r in previous.get("runs", [])
        if r.get("label", _label(r)) not in {run["label"] for run in recorded}
    ]
    manifest = {
        "recorded_at": previous.get("recorded_at") or now,
        **({"partly_recorded_at": now} if previous else {}),
        "runs": [{"label": r.get("label", _label(r)), **r} for r in kept] + recorded,
        "files": files,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(files)} files into {HERE}")


if __name__ == "__main__":
    main()
