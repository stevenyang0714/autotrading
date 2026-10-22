"""Record the TWSE OpenAPI files of the day as one more fixture day (opt-in; network).

    cd apps/api && uv run python -m tests.fixtures.twse.record [--companies]

Fetches the five daily files (and the company file with --companies) through the real client,
one request every 3 seconds, and appends them unmodified to manifest.json as day `dN`, with the
session STOCK_DAY_ALL names. Run it on a later Taipei day than the last recorded one (each file
holds only the latest session); a repeated session is refused.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from autotrading.adapters.twse.client import (
    COMPANIES,
    DAY,
    EX_RIGHTS,
    HOLIDAYS,
    MARGIN,
    VALUATION,
    TwseClient,
)
from autotrading.domain.twse import day_rows, session_of

HERE = Path(__file__).resolve().parent
NAMES = {
    DAY: "STOCK_DAY_ALL",
    VALUATION: "BWIBBU_d",
    MARGIN: "MI_MARGN",
    EX_RIGHTS: "TWT48U_ALL",
    HOLIDAYS: "holidaySchedule",
    COMPANIES: "t187ap03_L",
}
SPACING_SECONDS = 3.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    label = f"d{len(manifest['days']) + 1}"
    paths = [DAY, VALUATION, MARGIN, EX_RIGHTS, HOLIDAYS] + ([COMPANIES] if args.companies else [])
    fetched = {}
    with TwseClient() as client:
        for path in paths:
            fetched[path] = client.get(path, lambda: time.sleep(SPACING_SECONDS))
    session = session_of(day_rows(json.loads(fetched[DAY].content)))
    if str(session) in {d["session"] for d in manifest["days"]}:
        print(f"Session {session} is recorded already: nothing written.")
        return 1
    files = {}
    for path, payload in fetched.items():
        name = f"{label}_{NAMES[path]}.json"
        (HERE / name).write_bytes(payload.content)
        files[payload.source_url] = name
    manifest["days"].append(
        {
            "label": label,
            "session": str(session),
            "fetched_at": min(p.fetched_at for p in fetched.values()).isoformat(),
            "files": files,
        }
    )
    (HERE / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Recorded {label}: session {session}, {len(files)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
