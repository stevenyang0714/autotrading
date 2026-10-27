"""Record real FinMind responses as test fixtures (opt-in; network, anonymous free tier).

    cd apps/api && uv run python -m tests.fixtures.finmind.record

Fetches, through the real client at one request every 13 seconds (under the 300-an-hour cap):
- the six datasets for 2330 and 2317 over 2026-10-01..2026-10-22 (the TWSE fixture sessions
  2026-10-21 and 2026-10-22 lie inside, for the unit comparison, TW19);
- the ex-dividend results of 2330 and 2881 since 2016 (息 rows, and 2881's 權 rows, TW20).
Writes each response unmodified and manifest.json (URL -> file, fetched_at, attribution).
"""

import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

from autotrading.adapters.finmind.client import (
    ATTRIBUTION,
    DIVIDENDS,
    INSTITUTIONAL,
    MARGIN,
    PER,
    PRICE,
    SHAREHOLDING,
    FinMindClient,
)

HERE = Path(__file__).resolve().parent
WINDOW = (date(2026, 10, 1), date(2026, 10, 22))
HISTORY = (date(2016, 1, 1), date(2026, 10, 26))
REQUESTS: list[tuple[str, str, date, date]] = [
    *(
        (dataset, code, *WINDOW)
        for code in ("2330", "2317")
        for dataset in (PRICE, MARGIN, PER, INSTITUTIONAL, SHAREHOLDING)
    ),
    (DIVIDENDS, "2330", *HISTORY),
    (DIVIDENDS, "2881", *HISTORY),
    (DIVIDENDS, "2317", *HISTORY),
]
SPACING_SECONDS = 13.0


def main() -> int:
    files: dict[str, str] = {}
    fetched: list[datetime] = []
    with FinMindClient() as client:
        for i, (dataset, code, start, end) in enumerate(REQUESTS):
            if i:
                time.sleep(SPACING_SECONDS)
            payload = client.get(dataset, code, start, end, lambda: None)
            name = f"{code}_{dataset}.json"
            (HERE / name).write_bytes(payload.content)
            files[payload.source_url] = name
            fetched.append(payload.fetched_at)
            rows = json.loads(payload.content)["data"]
            print(f"{name}: {len(rows)} rows")
    manifest = {
        "note": (
            "Real FinMind API responses, unmodified, recorded with "
            "`uv run python -m tests.fixtures.finmind.record` (free anonymous tier). 2330 and "
            "2317 over 2026-10-01..2026-10-22; ex-dividend results since 2016 for 2330, 2881 "
            "and 2317."
        ),
        "attribution": ATTRIBUTION,
        "terms": "https://finmind.github.io/Pricing/",
        "recorded_at": min(fetched).astimezone(UTC).isoformat(),
        "files": files,
    }
    (HERE / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Recorded {len(files)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
