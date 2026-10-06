"""Acceptance times of new filings come from their EDGAR headers (ADR-013 amendment, 2026-10-06).

`acceptanceDateTime` in the submissions JSON was true UTC until 2026-10-05. On 2026-10-06 SEC
began returning many values 4 hours (EDT) or 5 hours (EST) late, the New York offset applied
twice, and not uniformly: in one file some rows are late and others correct (JPMorgan's newest
filing was right while its March filings were 5 hours late). AAPL's 8-K 0000320193-26-000018
reads 2026-07-31T00:30:28Z, while its header says `<ACCEPTANCE-DATETIME>20260730163028`
(16:30:28 New York, i.e. 20:30:28Z).

So the JSON value is never trusted for a filing we have not stored yet:
- filings already stored keep their stored time (stored before the bug, checked in ADR-013);
- every new 10-K, 10-Q or 8-K (and amendments) takes its time from its `.hdr.sgml` header; a
  missing header fails the run, because these times date the financial facts and earnings;
- other new filings (424B2, Form 4, ...) are checked the same way up to OTHER_FORMS_PER_RUN per
  run, newest first; beyond that they are stored date-only (end of the filing day in New York),
  which is never early.
"""

import re
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from autotrading.adapters.sec.parsing import SEC_ARCHIVES, FilingRecord

EASTERN = ZoneInfo("America/New_York")
HEADER_ACCEPTANCE = re.compile(rb"<ACCEPTANCE-DATETIME>(\d{14})")
# Forms whose acceptance time dates facts (XBRL) or market-moving events (earnings 8-Ks).
TIMED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "8-K12B", "8-K12B/A"})
OTHER_FORMS_PER_RUN = 200


class AcceptanceCheckError(RuntimeError):
    """A new filing's acceptance time could not be confirmed from its EDGAR header."""


def header_url(cik: str, accession: str) -> str:
    return f"{SEC_ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{accession}.hdr.sgml"


def header_acceptance(content: bytes) -> datetime | None:
    """`<ACCEPTANCE-DATETIME>20260730163028` is New York wall time."""
    match = HEADER_ACCEPTANCE.search(content)
    if match is None:
        return None
    wall = datetime.strptime(match.group(1).decode(), "%Y%m%d%H%M%S")
    return wall.replace(tzinfo=EASTERN).astimezone(UTC)


def eastern_offset(instant: datetime) -> timedelta:
    """How far New York is behind UTC at `instant`: 4 hours (EDT) or 5 hours (EST)."""
    offset = instant.astimezone(EASTERN).utcoffset()
    assert offset is not None
    return -offset


def to_check(
    records: Iterable[FilingRecord], known: set[str], other_limit: int = OTHER_FORMS_PER_RUN
) -> list[FilingRecord]:
    """New filings whose header to fetch: every timed form, then other forms newest first."""
    new = [r for r in records if r.accession_number not in known]
    timed = [r for r in new if r.form in TIMED_FORMS]
    others = sorted(
        (r for r in new if r.form not in TIMED_FORMS),
        key=lambda r: (r.filing_date, r.accession_number),
        reverse=True,
    )
    return timed + others[:other_limit]


class HeaderCheck:
    """Applies header times to new filings and counts what differed, for the run's note."""

    def __init__(self, headers: dict[str, datetime], other_limit: int = OTHER_FORMS_PER_RUN):
        self.headers = headers  # accession -> header acceptance time
        self.other_limit = other_limit
        self.checked = 0
        self.late_by_offset = 0
        self.other_difference = 0
        self.date_only = 0

    def apply(self, record: FilingRecord) -> FilingRecord:
        header = self.headers.get(record.accession_number)
        if header is None:
            if record.form in TIMED_FORMS:
                raise AcceptanceCheckError(
                    f"no EDGAR header acceptance time for {record.form} {record.accession_number}"
                )
            self.date_only += 1
            return replace(record, accepted_at=None)
        self.checked += 1
        if record.accepted_raw is not None and record.accepted_raw != header:
            if record.accepted_raw - header == eastern_offset(header):
                self.late_by_offset += 1
            else:
                self.other_difference += 1
        return replace(record, accepted_at=header)

    def note(self) -> str | None:
        if not (self.late_by_offset or self.other_difference or self.date_only):
            return None
        parts = [f"{self.checked} new filings timed from their EDGAR headers"]
        if self.late_by_offset:
            parts.append(f"{self.late_by_offset} JSON times were late by the New York offset")
        if self.other_difference:
            parts.append(f"{self.other_difference} JSON times differed otherwise")
        if self.date_only:
            parts.append(
                f"{self.date_only} other new filings beyond {self.other_limit} per run "
                "stored date-only"
            )
        return "; ".join(parts)
