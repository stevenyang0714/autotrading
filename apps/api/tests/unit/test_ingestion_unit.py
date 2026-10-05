from datetime import UTC, datetime
from typing import ClassVar

import pytest

from autotrading.ingestion.errors import MAX_MESSAGE_LENGTH, sanitize_error
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    JobRegistry,
    StoreContext,
    StoreResult,
    Window,
    idempotency_key,
    register_job,
)
from autotrading.ingestion.raw_store import object_key

JAN = Window(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC))


def test_idempotency_key_ignores_param_order() -> None:
    first = idempotency_key("sec_edgar", "sec.facts", {"cik": "1", "form": "10-K"}, JAN)
    second = idempotency_key("sec_edgar", "sec.facts", {"form": "10-K", "cik": "1"}, JAN)
    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    ("source", "job", "params", "window"),
    [
        ("fred", "sec.facts", {"cik": "1"}, JAN),
        ("sec_edgar", "sec.filings", {"cik": "1"}, JAN),
        ("sec_edgar", "sec.facts", {"cik": "2"}, JAN),
        ("sec_edgar", "sec.facts", {"cik": "1"}, Window()),
    ],
)
def test_idempotency_key_changes_with_any_input(
    source: str, job: str, params: dict[str, str], window: Window
) -> None:
    base = idempotency_key("sec_edgar", "sec.facts", {"cik": "1"}, JAN)
    assert idempotency_key(source, job, params, window) != base


def test_sanitize_error_redacts_credentials() -> None:
    exc = RuntimeError(
        "GET https://api.example.com/series?series_id=CPI&api_key=abc123&file_type=json failed; "
        "db postgresql://app:hunter2@db:5432/x"
    )
    error_class, message = sanitize_error(exc)
    assert error_class == "RuntimeError"
    assert "abc123" not in message and "api_key=***" in message
    assert "hunter2" not in message
    assert "series_id=CPI" in message  # non-secret context stays


def test_sanitize_error_truncates() -> None:
    _, message = sanitize_error(ValueError("x" * 5000))
    assert len(message) == MAX_MESSAGE_LENGTH


def test_raw_object_key_is_content_addressed() -> None:
    sha = "ab" + "0" * 62
    assert object_key("sec_edgar", sha) == f"raw/sec_edgar/ab/{sha}"


class _Job(IngestionJob):
    source_id: ClassVar[str] = "test_source"
    name: ClassVar[str] = "test.job"

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        return []

    def store(self, ctx: StoreContext) -> StoreResult:
        return StoreResult(0, 0)


def test_job_names_are_unique_in_a_registry() -> None:
    registry: JobRegistry = {}
    register_job(_Job, registry)
    register_job(_Job, registry)  # same class again is fine

    class Other(_Job):
        pass

    with pytest.raises(ValueError, match="already registered"):
        register_job(Other, registry)
