"""Re-record the SEC fixtures from the live API (opt-in, needs SEC_USER_AGENT in .env).

    cd apps/api && uv run python -m tests.fixtures.sec.record [--eight-ks]

Writes real responses, trimmed only where noted in manifest.json:
- tickers: company_tickers_exchange.json, rows of the universe equities only;
- companies: Apple (CIK 0000320193), ExxonMobil Holdings Corp (0002115436) and its
  predecessor Exxon Mobil Corp (0000034088, ADR-014), and Meta Platforms (0001326801), whose
  share counts are tagged per class only (ADR-021);
- company facts: only the concepts in adapters/sec/concepts.py (us-gaap, dei, srt);
- Exxon Mobil Corp and Meta submissions: only periodic and current reports plus every filing
  their XBRL facts cite (their full indexes are mostly Form 4 and proxy material).
Fails if the cases the integration tests rely on are no longer in the data.

Filing XBRL instances (ADR-021): Apple's latest 10-K and 10-Q, and Meta's latest 10-K and
10-Q plus its first inline XBRL 10-Q, trimmed to the mapped and identity concepts with the
contexts and units they use.

8-Ks for buyback announcements (M1.4a, ADR-025): the index-headers page, the 8-K and its EX-99
exhibits of the filings in EIGHT_KS, unchanged. `--eight-ks` records only these and keeps the
rest of the manifest as it is.

Submissions already recorded are kept: they were recorded on 2026-10-05, before SEC's
acceptance-time bug, and checked against EDGAR index pages (ADR-013). A company recorded for
the first time gets every row's acceptance time from its EDGAR header, because SEC's JSON is
unreliable since 2026-10-06 (adapters/sec/acceptance.py). Delete a company's submissions files
to record them again.
"""

import io
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from autotrading.adapters.sec.acceptance import header_acceptance, header_url
from autotrading.adapters.sec.client import SecClient
from autotrading.adapters.sec.company import (
    companyfacts_url,
    submissions_page_url,
    submissions_url,
)
from autotrading.adapters.sec.concepts import MAPPED_CONCEPTS, split_concept
from autotrading.adapters.sec.eight_k import INDEX_SUFFIX, folder_url, read_documents
from autotrading.adapters.sec.instance import (
    IDENTITY_CONCEPTS,
    TAXONOMY_URI,
    XBRLI,
    instance_url,
)
from autotrading.adapters.sec.parsing import load_companyfacts, parse_company, select_values
from autotrading.adapters.sec.refresh import INLINE_XBRL_SINCE, universe_equities
from autotrading.adapters.sec.tickers import TICKERS_URL
from autotrading.settings import get_settings

HERE = Path(__file__).resolve().parent
APPLE, XOM_HOLDINGS, EXXON_MOBIL, META = "0000320193", "0002115436", "0000034088", "0001326801"
PERIODIC_AND_CURRENT = frozenset(
    {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "8-K12B", "8-K12B/A"}
)
# CIK -> trim the submissions index to these forms (None: keep every filing).
COMPANIES: dict[str, frozenset[str] | None] = {
    APPLE: None,
    XOM_HOLDINGS: None,
    EXXON_MOBIL: PERIODIC_AND_CURRENT,
    META: PERIODIC_AND_CURRENT,
}
KEPT: dict[str, frozenset[str]] = {}  # taxonomy -> concept names kept in company facts
for _concept in MAPPED_CONCEPTS:
    _taxonomy, _name = split_concept(_concept)
    KEPT[_taxonomy] = KEPT.get(_taxonomy, frozenset()) | {_name}
# 8-Ks read for buyback announcements: authorization increases (Apple 2024 and 2026, Meta 2024
# with a remaining amount), a yearly plan (Exxon Mobil Corp, B9), and an 8.01 notice without one.
EIGHT_KS: dict[str, tuple[str, ...]] = {
    APPLE: ("0000320193-24-000067", "0001140361-25-018400", "0000320193-26-000011"),
    META: ("0001326801-24-000010",),
    EXXON_MOBIL: ("0000034088-25-000059",),
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
    previous: dict[str, Any] = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
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
            facts["facts"] = {
                taxonomy: {k: v for k, v in concepts.items() if k in KEPT[taxonomy]}
                for taxonomy, concepts in facts["facts"].items()
                if taxonomy in KEPT
            }
            name = f"companyfacts_CIK{cik}.json"
            files[companyfacts_url(cik)] = write(name, _dump(facts))
            trimmed[name] = "concepts limited to adapters/sec/concepts.py"
            cited = {v.accession for v in select_values(facts)}

            if (HERE / f"submissions_CIK{cik}.json").exists():
                kept = {
                    url: name
                    for url, name in previous["files"].items()
                    if f"CIK{cik}" in url and "/submissions/" in url
                }
                files.update(kept)
                trimmed.update(
                    {n: previous["trimmed"][n] for n in kept.values() if n in previous["trimmed"]}
                )
                continue
            main_page = client.get(submissions_url(cik), throttle)
            data = json.loads(main_page.content)
            pages = {
                page: json.loads(client.get(submissions_page_url(page), throttle).content)
                for page in parse_company(data).extra_pages
            }
            note = "acceptanceDateTime of every row from its EDGAR header (ADR-013 amendment)"
            if forms is not None:
                data["filings"]["recent"] = _keep(data["filings"]["recent"], forms, cited)
                pages = {page: _keep(block, forms, cited) for page, block in pages.items()}
                note = (
                    f"filings limited to forms {sorted(forms)} and accessions its facts cite; "
                    + note
                )
            for block in [data["filings"]["recent"], *pages.values()]:
                _header_times(client, cik, block)
            for page in [f"submissions_CIK{cik}.json", *pages]:
                trimmed[page] = note
            files[submissions_url(cik)] = write(f"submissions_CIK{cik}.json", _dump(data))
            for page, block in pages.items():
                files[submissions_page_url(page)] = write(page, _dump(block))

        instances = record_instances(client, files, trimmed)
        eight_ks = record_eight_ks(client, files)

    _check_restatement(load_companyfacts((HERE / f"companyfacts_CIK{APPLE}.json").read_bytes()))
    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": files,
        "trimmed": trimmed,
        "instances": instances,
        "eight_ks": eight_ks,
        "restatement_case": RESTATEMENT,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(files)} files into {HERE}")


def record_eight_ks(client: SecClient, files: dict[str, str]) -> list[str]:
    """The index page, 8-K and EX-99 exhibits of every filing in EIGHT_KS; returns their
    accessions."""
    for cik, accessions in EIGHT_KS.items():
        for accession in accessions:
            folder = folder_url(cik, accession)
            index = client.get(f"{folder}/{accession}{INDEX_SUFFIX}", throttle)
            files[index.source_url] = write(f"{accession}{INDEX_SUFFIX}", index.content)
            for _, name in read_documents(index.content):
                document = client.get(f"{folder}/{name}", throttle)
                files[document.source_url] = write(f"{accession}_{name}", document.content)
    return [a for accessions in EIGHT_KS.values() for a in accessions]


def main_eight_ks() -> None:
    """Record only the 8-Ks; every other file of the manifest stays as recorded."""
    manifest: dict[str, Any] = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    with SecClient.from_settings(get_settings()) as client:
        manifest["eight_ks"] = record_eight_ks(client, manifest["files"])
    manifest["eight_ks_recorded_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(manifest['eight_ks'])} 8-Ks into {HERE}")


def record_instances(
    client: SecClient, files: dict[str, str], trimmed: dict[str, str]
) -> list[str]:
    """Instances of the filings listed in the module docstring; returns their accessions."""
    chosen: list[tuple[str, str, str]] = []  # (cik, accession, primary document)
    for cik, first_too in ((APPLE, False), (META, True)):
        rows = []
        for url, name in files.items():
            if f"CIK{cik}" in url and "/submissions/" in url:
                data = json.loads((HERE / name).read_bytes())
                block = data["filings"]["recent"] if "filings" in data else data
                rows += [
                    (block["filingDate"][i], block["form"][i], a, block["primaryDocument"][i])
                    for i, a in enumerate(block["accessionNumber"])
                    if block["form"][i] in ("10-K", "10-Q") and block["isInlineXBRL"][i]
                ]
        rows.sort(reverse=True)
        picks = [next(r for r in rows if r[1] == form) for form in ("10-K", "10-Q")]
        if first_too:
            picks.append(min(r for r in rows if r[0] >= INLINE_XBRL_SINCE.isoformat()))
        chosen += [(cik, accession, document) for _, _, accession, document in picks]
    for cik, accession, document in chosen:
        url = instance_url(cik, accession, document)
        name = f"{accession}_instance.xml"
        files[url] = write(name, _trimmed_instance(client.get(url, throttle).content))
        trimmed[name] = (
            "facts limited to mapped and identity concepts, with their contexts and units"
        )
    return [accession for _, accession, _ in chosen]


def _trimmed_instance(content: bytes) -> bytes:
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(content), events=["start-ns"]):
        if prefix:
            ET.register_namespace(prefix, uri)
    root = ET.fromstring(content)
    keep = MAPPED_CONCEPTS | IDENTITY_CONCEPTS
    contexts, units = set(), set()
    for element in list(root):
        if element.get("contextRef") is None:
            continue
        namespace, _, name = element.tag[1:].partition("}")
        match = TAXONOMY_URI.match(namespace)
        if match and f"{match.group(1) or match.group(2)}:{name}" in keep:
            contexts.add(element.get("contextRef"))
            if element.get("unitRef"):
                units.add(element.get("unitRef"))
        else:
            root.remove(element)
    for element in list(root):
        if (
            (element.tag == f"{XBRLI}context" and element.get("id") not in contexts)
            or (element.tag == f"{XBRLI}unit" and element.get("id") not in units)
            or element.tag.endswith("}footnoteLink")
        ):
            root.remove(element)
    return bytes(ET.tostring(root, xml_declaration=True, encoding="utf-8"))


def _header_times(client: SecClient, cik: str, block: dict[str, list[Any]]) -> None:
    """Replace each row's acceptanceDateTime with the time in the filing's EDGAR header."""
    for i, accession in enumerate(block["accessionNumber"]):
        accepted = header_acceptance(client.get(header_url(cik, accession), throttle).content)
        if accepted is None:
            raise SystemExit(f"no acceptance time in the EDGAR header of {accession}")
        block["acceptanceDateTime"][i] = accepted.strftime("%Y-%m-%dT%H:%M:%S.000Z")


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
    main_eight_ks() if "--eight-ks" in sys.argv else main()
