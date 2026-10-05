"""Builders for valid domain objects; tests override only what they exercise."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from autotrading.domain.facts import FinancialFactIn
from autotrading.domain.provenance import Provenance

TEST_SOURCE_ID = "test_source"


def provenance(**overrides: Any) -> Provenance:
    fields: dict[str, Any] = {
        "source_id": TEST_SOURCE_ID,
        "source_tier": 1,
        "source_url": "https://www.sec.gov/Archives/edgar/data/0000000000/example.htm",
        "published_at": datetime(2025, 2, 1, 21, 5, tzinfo=UTC),
        "published_at_precision": "exact",
        "ingested_at": datetime(2026, 10, 5, 3, 0, tzinfo=UTC),
        "effective_from": datetime(2024, 10, 1, tzinfo=UTC),
        "effective_to": datetime(2024, 12, 31, tzinfo=UTC),
        "as_of": datetime(2024, 12, 31, tzinfo=UTC),
        "license_status": "public",
        "confidence": 1.0,
        "source_timezone": "America/New_York",
    }
    fields.update(overrides)
    return Provenance(**fields)


def financial_fact(
    *,
    entity_id: UUID | None = None,
    value: str = "100",
    metric_id: str = "revenue",
    provenance_overrides: dict[str, Any] | None = None,
    **overrides: Any,
) -> FinancialFactIn:
    fields: dict[str, Any] = {
        "entity_id": entity_id or uuid4(),
        "metric_id": metric_id,
        "value": Decimal(value),
        "unit": "USD",
        "currency": "USD",
        "fiscal_period": "Q4-2024",
        "period_start": date(2024, 10, 1),
        "period_end": date(2024, 12, 31),
        "accession_id": "0000000000-25-000001",
        "provenance": provenance(**(provenance_overrides or {})),
    }
    fields.update(overrides)
    return FinancialFactIn(**fields)
