"""Record real FinMind TaiwanStockPrice responses for the Taiwan screens (M3.11, ADR-042; opt-in;
network, anonymous free tier).

    cd apps/api && uv run python -m tests.fixtures.finmind_prices.record

Fetches, through the real client at one request every 13 seconds (under the 300-an-hour cap):
- 2330 over 2025-06-01..2026-10-22: several ex-dividend sessions (息), for the check that
  `spread` is the change against the reference price (SC6) against the recorded ex-dividend
  results (tests/fixtures/finmind);
- 2881 over 2024-06-01..2026-10-22: its ex-rights sessions (權);
- 2454, 3711, 2303 and 2408 over 2026-01-01..2026-10-22: with 2330, five semiconductor
  companies (industry 24) with enough sessions for every screen reading.
Writes each response unmodified and manifest.json (URL -> file, fetched_at, attribution).
"""

import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

from autotrading.adapters.finmind.client import ATTRIBUTION, PRICE, FinMindClient

HERE = Path(__file__).resolve().parent
END = date(2026, 10, 22)
REQUESTS: list[tuple[str, date, date]] = [
    ("2330", date(2025, 6, 1), END),
    ("2881", date(2024, 6, 1), END),
    *((code, date(2026, 1, 1), END) for code in ("2454", "3711", "2303", "2408")),
]
SPACING_SECONDS = 13.0


def main() -> int:
    files: dict[str, str] = {}
    fetched: list[datetime] = []
    with FinMindClient() as client:
        for i, (code, start, end) in enumerate(REQUESTS):
            if i:
                time.sleep(SPACING_SECONDS)
            payload = client.get(PRICE, code, start, end, lambda: None)
            name = f"{code}_{PRICE}.json"
            (HERE / name).write_bytes(payload.content)
            files[payload.source_url] = name
            fetched.append(payload.fetched_at)
            rows = json.loads(payload.content)["data"]
            print(f"{name}: {len(rows)} rows, {rows[0]['date']}..{rows[-1]['date']}")
    manifest = {
        "note": (
            "Real FinMind API responses, unmodified, recorded with "
            "`uv run python -m tests.fixtures.finmind_prices.record` (free anonymous tier): "
            "TaiwanStockPrice of 2330 since 2025-06-01, 2881 since 2024-06-01, and 2454, 3711, "
            "2303 and 2408 since 2026-01-01, all to 2026-10-22."
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
