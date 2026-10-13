"""Re-record the FRED fixtures from the live API (opt-in, needs FRED_API_KEY in .env).

    cd apps/api && uv run python -m tests.fixtures.fred.record [--only NFCI,STLFSI4]

Runs the real `fred.series` fetch (series record, vintage dates, observations over every
vintage) for every series in config/macro_series.yaml, so the recorded URLs are exactly what
replay requests. Observations start in 2023 (monthly, quarterly) or mid-2025 (daily) through
`observation_start` to keep the files small; everything else is the unmodified response.
URLs in manifest.json never contain the API key (ADR-015). Also picks a real revision case
for the integration tests and fails if none exists.

`--only` records the named series and merges them into the existing manifest, leaving every
other series' files (and the values tests pin on them) untouched (M2.1).
"""

import argparse
import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from autotrading.adapters.fred.series import FredSeriesJob, payload_kind
from autotrading.ingestion.job import FetchContext, Window
from autotrading.settings import get_settings

HERE = Path(__file__).resolve().parent
MONTHLY_START, DAILY_START, WEEKLY_START = "2023-01-01", "2025-06-01", "2025-01-01"
# Series -> first observation date recorded. Enough for 36-month charts, 12-month changes and
# the Sahm rule (monthly), 12 quarters (GDP) and one year of daily data.
SERIES = {
    "CPIAUCSL": MONTHLY_START,
    "PCEPILFE": MONTHLY_START,
    "UNRATE": MONTHLY_START,
    "PAYEMS": MONTHLY_START,
    "GDPC1": MONTHLY_START,
    "FEDFUNDS": MONTHLY_START,
    "DGS2": DAILY_START,
    "DGS10": DAILY_START,
    "T10Y2Y": DAILY_START,
    "BAMLH0A0HYM2": DAILY_START,
    "VIXCLS": DAILY_START,
    # Regime inputs (M2.1). The weekly indices revise their whole history every week, so a
    # shorter recording keeps the files small.
    "VXVCLS": DAILY_START,
    "NFCI": WEEKLY_START,
    "NFCICREDIT": WEEKLY_START,
    "STLFSI4": WEEKLY_START,
    "DCOILWTICO": DAILY_START,
    "DTWEXBGS": DAILY_START,
}


def throttle() -> None:
    time.sleep(0.6)  # under the configured 1 request/second


def selected(only: str | None) -> dict[str, str]:
    """The series to record: all, or the comma-separated `only` (each must be in SERIES)."""
    if not only:
        return dict(SERIES)
    wanted = [s.strip() for s in only.split(",") if s.strip()]
    unknown = [s for s in wanted if s not in SERIES]
    if unknown:
        raise SystemExit(f"not in SERIES: {unknown}")
    return {s: SERIES[s] for s in wanted}


def merged(old: dict[str, Any], files: dict[str, str], series: dict[str, str]) -> dict[str, Any]:
    """The manifest with `series` re-recorded: their old files dropped, everything else kept."""
    kept = {url: name for url, name in old["files"].items() if name.split("_")[0] not in series}
    return {
        **old,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "observation_start": {**old["observation_start"], **series},
        "files": {**kept, **files},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated series to record and merge")
    args = parser.parse_args()
    series = selected(args.only)
    key = get_settings().fred_api_key
    files: dict[str, str] = {}
    for series_id, start in series.items():
        job = FredSeriesJob({"series_id": series_id, "observation_start": start}, Window())
        for i, payload in enumerate(job.fetch(FetchContext(run_id=uuid4(), acquire=throttle))):
            name = f"{series_id}_{i:02d}_{payload_kind(payload.source_url)}.json"
            (HERE / name).write_bytes(payload.content)
            files[payload.source_url] = name
    secret = key.get_secret_value() if key else ""
    for name in files.values():
        if secret and secret in (HERE / name).read_text(encoding="utf-8"):
            raise SystemExit(f"API key found in {name}; not writing the manifest")
    if secret and any(secret in url for url in files):
        raise SystemExit("API key found in a URL; not writing the manifest")

    if args.only:
        old = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
        manifest = merged(old, files, series)
    else:
        manifest = {
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "observation_start": SERIES,
            "files": files,
            "revision_case": _revision_case("PAYEMS", files),
        }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(files)} files into {HERE}")


def _revision_case(series_id: str, files: dict[str, str]) -> dict[str, Any]:
    """The newest observation whose first release differs from today's value."""
    vintages: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for url, name in files.items():
        if name.startswith(series_id) and payload_kind(url) == "observations":
            for row in json.loads((HERE / name).read_text(encoding="utf-8"))["observations"]:
                if row["value"] != ".":
                    vintages[row["date"]].append((row["realtime_start"], row["value"]))
    for day in sorted(vintages, reverse=True):
        versions = sorted(set(vintages[day]))
        if versions[0][1] != versions[-1][1]:
            first, revised = versions[0], next(v for v in versions if v[1] != versions[0][1])
            return {
                "series_id": series_id,
                "observation_date": day,
                "first_release": {"vintage": first[0], "value": first[1]},
                "first_revision": {"vintage": revised[0], "value": revised[1]},
                "latest": {"vintage": versions[-1][0], "value": versions[-1][1]},
            }
    raise SystemExit(f"no revised observation found in {series_id}")


if __name__ == "__main__":
    main()
