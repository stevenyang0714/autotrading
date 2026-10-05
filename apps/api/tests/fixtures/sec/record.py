"""Re-record the SEC fixtures from the live API (opt-in, needs SEC_USER_AGENT in .env).

    cd apps/api && uv run python -m tests.fixtures.sec.record

Writes real responses, trimmed only where noted in manifest.json:
- tickers: company_tickers_exchange.json, rows of the universe equities only;
- Apple (CIK 0000320193): submissions and its older filings page, unchanged;
- Apple company facts: only the us-gaap concepts in adapters/sec/concepts.py.
Fails if the restatement case the integration tests rely on is no longer in the data.
"""

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import (
    companyfacts_url,
    submissions_page_url,
    submissions_url,
)
from autotrading.adapters.sec.concepts import MAPPED_CONCEPTS, TAXONOMY
from autotrading.adapters.sec.parsing import load_companyfacts, parse_company, select_values
from autotrading.adapters.sec.refresh import universe_equities
from autotrading.adapters.sec.tickers import TICKERS_URL
from autotrading.settings import get_settings

HERE = Path(__file__).resolve().parent
CIK = "0000320193"
# Apple FY2008 net income: 10-K (Oct 2009) vs 10-K/A (Jan 2010) after the revenue
# recognition change for iPhone and Apple TV.
RESTATEMENT = {
    "metric_id": "net_income",
    "period": ["2007-09-30", "2008-09-27"],
    "original": {"accession": "0001193125-09-214859", "value": "4834000000"},
    "restated": {"accession": "0001193125-10-012091", "value": "6119000000"},
}


def throttle() -> None:
    time.sleep(0.25)  # 4 requests/second, under the configured 5


def write(name: str, content: bytes) -> str:
    (HERE / name).write_bytes(content)
    return name


def main() -> None:
    settings = get_settings()
    files: dict[str, str] = {}
    with SecClient.from_settings(settings) as client:
        tickers = json.loads(client.get(TICKERS_URL, throttle).content)
        universe = set(universe_equities(settings.resolved_config_dir()))
        tickers["data"] = [row for row in tickers["data"] if row[2] in universe]
        files[TICKERS_URL] = write("company_tickers_exchange.json", _dump(tickers))

        main_page = client.get(submissions_url(CIK), throttle)
        files[main_page.source_url] = write(f"submissions_CIK{CIK}.json", main_page.content)
        for name in parse_company(json.loads(main_page.content)).extra_pages:
            page = client.get(submissions_page_url(name), throttle)
            files[page.source_url] = write(name, page.content)

        facts = load_companyfacts(client.get(companyfacts_url(CIK), throttle).content)
        gaap = facts["facts"][TAXONOMY]
        facts["facts"] = {TAXONOMY: {k: v for k, v in gaap.items() if k in MAPPED_CONCEPTS}}
        files[companyfacts_url(CIK)] = write(f"companyfacts_CIK{CIK}.json", _dump(facts))

    _check_restatement(load_companyfacts((HERE / f"companyfacts_CIK{CIK}.json").read_bytes()))
    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": files,
        "trimmed": {
            "company_tickers_exchange.json": "data rows limited to config/universe.yaml equities",
            f"companyfacts_CIK{CIK}.json": "us-gaap concepts limited to adapters/sec/concepts.py",
        },
        "restatement_case": RESTATEMENT,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(files)} files into {HERE}")


def _dump(data: Any) -> bytes:
    return json.dumps(data, separators=(",", ":"), default=_decimal).encode()


def _decimal(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def _check_restatement(companyfacts: dict[str, Any]) -> None:
    start, end = RESTATEMENT["period"]
    found = {
        (v.accession, str(v.value))
        for v in select_values(companyfacts)
        if v.metric_id == RESTATEMENT["metric_id"]
        and str(v.period_start) == start
        and str(v.period_end) == end
    }
    for side in ("original", "restated"):
        case = RESTATEMENT[side]
        assert isinstance(case, dict)
        if (case["accession"], case["value"]) not in found:
            raise SystemExit(f"restatement case missing from the recording: {side} {case}")


if __name__ == "__main__":
    main()
