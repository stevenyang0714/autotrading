from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from autotrading.domain.provenance import Provenance, end_of_day
from tests.factories import financial_fact, provenance

REQUIRED = [
    "source_id",
    "source_tier",
    "source_url",
    "published_at",
    "published_at_precision",
    "ingested_at",
    "effective_from",
    "as_of",
    "license_status",
    "confidence",
]


def test_valid_provenance() -> None:
    assert provenance().source_tier == 1


@pytest.mark.parametrize("field", REQUIRED)
def test_missing_required_field_is_rejected(field: str) -> None:
    fields = provenance().model_dump()
    del fields[field]
    with pytest.raises(ValidationError, match=field):
        Provenance(**fields)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        provenance(published_at=datetime(2025, 2, 1, 21, 5))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", 1.5),
        ("confidence", -0.1),
        ("source_tier", 0),
        ("source_tier", 5),
        ("license_status", "scraped"),
        ("published_at_precision", "hour"),
        ("source_url", "ftp://example.com/file"),
        ("source_id", "Bad Source"),
        ("raw_payload_sha256", "not-a-hash"),
        ("source_timezone", "Mars/Olympus_Mons"),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        provenance(**{field: value})


def test_effective_to_before_effective_from_is_rejected() -> None:
    with pytest.raises(ValidationError, match="effective_to"):
        provenance(
            effective_from=datetime(2025, 1, 2, tzinfo=UTC),
            effective_to=datetime(2025, 1, 1, tzinfo=UTC),
        )


def test_instant_effective_range_is_allowed() -> None:
    instant = datetime(2024, 12, 31, tzinfo=UTC)
    assert provenance(effective_from=instant, effective_to=instant).effective_to == instant


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        provenance(note="extra")


def test_end_of_day_is_conservative_new_york_close() -> None:
    # ADR-012: a date-only publication is known only at the end of that New York day.
    assert end_of_day(date(2026, 9, 10)) == datetime(2026, 9, 11, 3, 59, 59, 999999, tzinfo=UTC)
    # Standard time (EST, UTC-5) after the November switch.
    assert end_of_day(date(2026, 12, 10)) == datetime(2026, 12, 11, 4, 59, 59, 999999, tzinfo=UTC)


def test_financial_fact_rejects_non_finite_values() -> None:
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValidationError):
            financial_fact(value=bad)


def test_financial_fact_rejects_inverted_period() -> None:
    with pytest.raises(ValidationError, match="period_start"):
        financial_fact(period_start=date(2025, 1, 1), period_end=date(2024, 12, 31))


def test_fact_key_ignores_fiscal_period() -> None:
    first = financial_fact(fiscal_period="FY2024")
    second = financial_fact(entity_id=first.entity_id, fiscal_period="FY2025")
    assert first.fact_key() == second.fact_key()
