"""Re-record the SEC fixtures from the live API (opt-in, needs SEC_USER_AGENT in .env).

    cd apps/api && uv run python -m tests.fixtures.sec.record

Writes real responses, trimmed only where noted in manifest.json:
- tickers: company_tickers_exchange.json, rows of the universe equities only;
- companies: Apple (CIK 0000320193), ExxonMobil Holdings Corp (0002115436) and its
  predecessor Exxon Mobil Corp (0000034088, ADR-014);
- company facts: only the us-gaap concepts in adapters/sec/concepts.py;
- Exxon Mobil Corp submissions: only periodic and current reports plus every filing its XBRL
  facts cite (its full index is mostly Form 4 and proxy material).
Fails if the cases the integration tests rely on are no longer in the data.
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
APPLE, XOM_HOLDINGS, EXXON_MOBIL = "0000320193", "0002115436", "0000034088"
# CIK -> trim the submissions index to these forms (None: keep every filing).
COMPANIES: dict[str, frozenset[str] | None] = {
    APPLE: None,
    XOM_HOLDINGS: None,
    EXXON_MOBIL: frozenset(
        {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "8-K12B", "8-K12B/A"}
    ),
}
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
    trimmed: dict[str, str] = {
        "company_tickers_exchange.json": "data rows limited to config/universe.yaml equities",
    }
    with SecClient.from_settings(settings) as client:
        tickers = json.loads(client.get(TICKERS_URL, throttle).content)
        universe = set(universe_equities(settings.resolved_config_dir()))
        tickers["data"] = [row for row in tickers["data"] if row[2] in universe]
        files[TICKERS_URL] = write("company_tickers_exchange.json", _dump(tickers))

        for cik, forms in COMPANIES.items():
            facts = load_companyfacts(client.get(companyfacts_url(cik), throttle).content)
            gaap = facts["facts"][TAXONOMY]
            facts["facts"] = {TAXONOMY: {k: v for k, v in gaap.items() if k in MAPPED_CONCEPTS}}
            name = f"companyfacts_CIK{cik}.json"
            files[companyfacts_url(cik)] = write(name, _dump(facts))
            trimmed[name] = "us-gaap concepts limited to adapters/sec/concepts.py"
            cited = {v.accession for v in select_values(facts)}

            main_page = client.get(submissions_url(cik), throttle)
            data = json.loads(main_page.content)
            pages = {
                page: json.loads(client.get(submissions_page_url(page), throttle).content)
                for page in parse_company(data).extra_pages
            }
            if forms is not None:
                data["filings"]["recent"] = _keep(data["filings"]["recent"], forms, cited)
                pages = {page: _keep(block, forms, cited) for page, block in pages.items()}
                note = f"filings limited to forms {sorted(forms)} and accessions its facts cite"
                for page in [f"submissions_CIK{cik}.json", *pages]:
                    trimmed[page] = note
            files[submissions_url(cik)] = write(f"submissions_CIK{cik}.json", _dump(data))
            for page, block in pages.items():
                files[submissions_page_url(page)] = write(page, _dump(block))

    _check_restatement(load_companyfacts((HERE / f"companyfacts_CIK{APPLE}.json").read_bytes()))
    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": files,
        "trimmed": trimmed,
        "restatement_case": RESTATEMENT,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(files)} files into {HERE}")


def _keep(block: dict[str, list[Any]], forms: frozenset[str], cited: set[str]) -> dict[str, Any]:
    """Rows of SEC's column layout whose form is wanted or whose accession facts cite."""
    rows = [
        i
        for i, (form, accession) in enumerate(
            zip(block["form"], block["accessionNumber"], strict=True)
        )
        if form in forms or accession in cited
    ]
    return {column: [values[i] for i in rows] for column, values in block.items()}


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
