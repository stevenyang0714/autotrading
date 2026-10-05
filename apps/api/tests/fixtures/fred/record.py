"""Re-record the FRED fixtures from the live API (opt-in, needs FRED_API_KEY in .env).

    cd apps/api && uv run python -m tests.fixtures.fred.record

Runs the real `fred.series` fetch (series record, vintage dates, observations over every
vintage), so the recorded URLs are exactly what replay requests. Observations start in 2023
(`observation_start`) to keep the files small; everything else is the unmodified response.
URLs in manifest.json never contain the API key (ADR-015). Also picks a real revision case
for the integration tests and fails if none exists.
"""

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
OBSERVATION_START = "2023-01-01"
SERIES = ("PAYEMS", "CPIAUCSL")


def throttle() -> None:
    time.sleep(0.6)  # under the configured 1 request/second


def main() -> None:
    key = get_settings().fred_api_key
    files: dict[str, str] = {}
    for series_id in SERIES:
        job = FredSeriesJob(
            {"series_id": series_id, "observation_start": OBSERVATION_START}, Window()
        )
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

    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "observation_start": OBSERVATION_START,
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
