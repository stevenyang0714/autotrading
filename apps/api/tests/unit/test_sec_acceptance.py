"""New filings are timed from their EDGAR headers (ADR-013 amendment, 2026-10-06)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from autotrading.adapters.sec.acceptance import (
    AcceptanceCheckError,
    HeaderCheck,
    eastern_offset,
    header_acceptance,
    header_url,
    to_check,
)
from autotrading.adapters.sec.parsing import FilingRecord

# AAPL's 8-K 0000320193-26-000018: header 16:30:28 New York (EDT) = 20:30:28 UTC.
TRUE_EDT = datetime(2026, 7, 30, 20, 30, 28, tzinfo=UTC)
# Apple's 10-K/A 0001193125-10-012091: header 16:25:58 New York (EST) = 21:25:58 UTC.
TRUE_EST = datetime(2010, 1, 25, 21, 25, 58, tzinfo=UTC)


def record(
    accession: str, form: str = "8-K", raw: datetime | None = TRUE_EDT, day: int = 30
) -> FilingRecord:
    return FilingRecord(
        cik="0000320193",
        accession_number=accession,
        form=form,
        filing_date=date(2026, 7, day),
        accepted_at=raw,
        report_date=None,
        primary_document=None,
        primary_doc_description=None,
        items=None,
        is_xbrl=False,
        is_inline_xbrl=False,
        accepted_raw=raw,
    )


def test_header_time_is_new_york_wall_time() -> None:
    header = b"<SEC-HEADER>\n<ACCEPTANCE-DATETIME>20260730163028\n<TYPE>8-K\n"
    assert header_acceptance(header) == TRUE_EDT
    assert header_acceptance(b"<ACCEPTANCE-DATETIME>20100125162558") == TRUE_EST
    assert header_acceptance(b"no header") is None


def test_header_url_is_the_filing_folder() -> None:
    assert header_url("0000320193", "0000320193-26-000018") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/"
        "0000320193-26-000018.hdr.sgml"
    )


def test_eastern_offset_follows_daylight_saving() -> None:
    assert eastern_offset(TRUE_EDT) == timedelta(hours=4)
    assert eastern_offset(TRUE_EST) == timedelta(hours=5)


def test_only_new_filings_are_checked_timed_forms_all_others_newest_first() -> None:
    records = [
        record("a-stored", "10-Q"),
        record("b-10q", "10-Q"),
        record("c-8k", "8-K"),
        record("d-424", "424B2", day=28),
        record("e-424", "424B2", day=29),
        record("f-4", "4", day=27),
    ]
    chosen = [r.accession_number for r in to_check(records, {"a-stored"}, other_limit=2)]
    assert chosen == ["b-10q", "c-8k", "e-424", "d-424"]


def test_header_time_replaces_the_json_time_and_the_difference_is_noted() -> None:
    late = record("x", raw=TRUE_EDT + timedelta(hours=4))  # SEC's 2026-10-06 bug
    right = record("y", raw=TRUE_EST)
    off = record("z", raw=TRUE_EDT + timedelta(minutes=7))
    check = HeaderCheck({"x": TRUE_EDT, "y": TRUE_EST, "z": TRUE_EDT})
    assert check.apply(late).published() == (TRUE_EDT, "exact")
    assert check.apply(right).accepted_at == TRUE_EST
    assert check.apply(off).accepted_at == TRUE_EDT
    note = check.note()
    assert note == (
        "3 new filings timed from their EDGAR headers; "
        "1 JSON times were late by the New York offset; 1 JSON times differed otherwise"
    )


def test_all_json_times_right_means_no_note() -> None:
    check = HeaderCheck({"y": TRUE_EST})
    check.apply(record("y", raw=TRUE_EST))
    assert check.note() is None


def test_a_timed_form_without_header_fails_the_run() -> None:
    with pytest.raises(AcceptanceCheckError, match="10-Q x"):
        HeaderCheck({}).apply(record("x", "10-Q"))


def test_other_forms_without_header_are_stored_date_only() -> None:
    check = HeaderCheck({}, other_limit=200)
    stored = check.apply(record("x", "424B2"))
    assert stored.accepted_at is None
    assert stored.published()[1] == "day"
    assert check.note() == (
        "0 new filings timed from their EDGAR headers; "
        "1 other new filings beyond 200 per run stored date-only"
    )
