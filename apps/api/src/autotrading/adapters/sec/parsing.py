"""Pure parsing of SEC submissions and XBRL company facts (no I/O, no database).

Time rules (ADR-013):
- `acceptanceDateTime` is true UTC. Checked against EDGAR index pages, which show Eastern
  time: AAPL's 8-K 0000320193-26-000018 is `2026-07-30T20:30:28.000Z` in JSON and
  "2026-07-30 16:30:28" on its index page.
- A filing is public from its acceptance time. Acceptances after 17:30 ET carry the next
  business day as filing date, so the date alone would be late, not early.
- An acceptance of exactly 00:00:00Z is a date-only placeholder (a handful of old FWPs);
  those and missing values fall back to the end of the filing date in New York (ADR-012).
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from autotrading.adapters.sec.concepts import METRIC_MAPPINGS, TAXONOMY, MetricMapping, qualified
from autotrading.domain.provenance import TimePrecision, end_of_day

SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
CIK = re.compile(r"^\d{10}$")


def normalize_cik(value: str | int) -> str:
    cik = f"{int(value):010d}"
    if not CIK.match(cik):
        raise ValueError(f"not a CIK: {value!r}")
    return cik


def filing_index_url(cik: str, accession: str) -> str:
    """EDGAR index page of a filing: lists every document, with acceptance time in ET."""
    return f"{SEC_ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"


def parse_acceptance(value: str | None) -> datetime | None:
    if not value:
        return None
    accepted = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    if accepted.time() == time(0, 0):
        return None  # date-only placeholder, see module docstring
    return accepted


def publication_time(
    accepted_at: datetime | None, filing_date: date
) -> tuple[datetime, TimePrecision]:
    if accepted_at is not None:
        return accepted_at, "exact"
    return end_of_day(filing_date), "day"


def midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=UTC)


# ---------- submissions ----------


@dataclass(frozen=True)
class FilingRecord:
    cik: str
    accession_number: str
    form: str
    filing_date: date
    accepted_at: datetime | None
    report_date: date | None
    primary_document: str | None
    primary_doc_description: str | None
    items: str | None
    is_xbrl: bool
    is_inline_xbrl: bool

    @property
    def index_url(self) -> str:
        return filing_index_url(self.cik, self.accession_number)

    def published(self) -> tuple[datetime, TimePrecision]:
        return publication_time(self.accepted_at, self.filing_date)


@dataclass(frozen=True)
class CompanyInfo:
    cik: str
    name: str
    tickers: list[str]
    exchanges: list[str]
    extra_pages: list[str]  # file names of older filing pages


def parse_company(submissions: dict[str, Any]) -> CompanyInfo:
    return CompanyInfo(
        cik=normalize_cik(submissions["cik"]),
        name=submissions["name"],
        tickers=list(submissions.get("tickers") or []),
        exchanges=[e or "" for e in submissions.get("exchanges") or []],
        extra_pages=[page["name"] for page in submissions["filings"].get("files", [])],
    )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _date(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def parse_filings(block: dict[str, list[Any]], cik: str) -> list[FilingRecord]:
    """One page of filings in SEC's column layout: `filings.recent` of the main document, or
    an older page file, which has the same columns at its top level."""
    records = []
    for i, accession in enumerate(block["accessionNumber"]):
        if not ACCESSION.match(accession) or not block["form"][i]:
            continue
        filing_date = _date(block["filingDate"][i])
        if filing_date is None:
            continue
        records.append(
            FilingRecord(
                cik=cik,
                accession_number=accession,
                form=block["form"][i],
                filing_date=filing_date,
                accepted_at=parse_acceptance(block["acceptanceDateTime"][i]),
                report_date=_date(block["reportDate"][i]),
                primary_document=_text(block["primaryDocument"][i]),
                primary_doc_description=_text(block["primaryDocDescription"][i]),
                items=_text(block["items"][i]),
                is_xbrl=bool(block["isXBRL"][i]),
                is_inline_xbrl=bool(block["isInlineXBRL"][i]),
            )
        )
    return records


# ---------- XBRL company facts ----------


@dataclass(frozen=True)
class XbrlValue:
    metric_id: str
    concept: str  # qualified, e.g. us-gaap:NetIncomeLoss
    unit: str
    currency: str | None
    value: Decimal
    period_start: date | None
    period_end: date
    accession: str
    filed: date
    fiscal_period: str | None  # SEC fp-fy of the filing, e.g. FY-2024; describes the filing
    form: str


def load_companyfacts(content: bytes) -> dict[str, Any]:
    """Decimal, not float: values are compared for equality across filings."""
    data: dict[str, Any] = json.loads(content, parse_float=Decimal)
    return data


def _observations(concept: dict[str, Any], mapping: MetricMapping) -> list[dict[str, Any]]:
    return list(concept.get("units", {}).get(mapping.unit, []))


def select_values(companyfacts: dict[str, Any]) -> list[XbrlValue]:
    """Values of the mapped metrics, one concept per (metric, filing, period).

    Observations in another unit (e.g. EPS tagged as `pure`) or of the wrong period type are
    ignored. Identical repeats are dropped; two different values for one filing and period
    are both returned and surface later as a conflict.
    """
    gaap: dict[str, Any] = companyfacts.get("facts", {}).get(TAXONOMY, {})
    selected: list[XbrlValue] = []
    for mapping in METRIC_MAPPINGS:
        # (accession, start, end) -> (priority, values from that concept)
        best: dict[tuple[str, str | None, str], tuple[int, list[XbrlValue]]] = {}
        for priority, concept in enumerate(mapping.concepts):
            if concept not in gaap:
                continue
            per_slot: dict[tuple[str, str | None, str], list[XbrlValue]] = defaultdict(list)
            for obs in _observations(gaap[concept], mapping):
                start = obs.get("start")
                if (mapping.period == "duration") != (start is not None):
                    continue
                slot = (obs["accn"], start, obs["end"])
                value = XbrlValue(
                    metric_id=mapping.metric_id,
                    concept=qualified(concept),
                    unit=mapping.unit,
                    currency=mapping.currency,
                    value=Decimal(obs["val"]),
                    period_start=_date(start),
                    period_end=date.fromisoformat(obs["end"]),
                    accession=obs["accn"],
                    filed=date.fromisoformat(obs["filed"]),
                    fiscal_period=(
                        f"{obs['fp']}-{obs['fy']}" if obs.get("fp") and obs.get("fy") else None
                    ),
                    form=obs.get("form", ""),
                )
                if all(v.value != value.value for v in per_slot[slot]):
                    per_slot[slot].append(value)
            for slot, values in per_slot.items():
                if slot not in best:
                    best[slot] = (priority, values)
        for _priority, values in best.values():
            selected.extend(values)
    return selected
