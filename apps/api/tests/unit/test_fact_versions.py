"""decide_version: which incoming values become new fact versions (ADR-012, M0.5)."""

from datetime import UTC, datetime
from decimal import Decimal

from autotrading.domain.facts import Conflict, NewVersion, StoredVersion, Unchanged, decide_version

OCT_2009 = datetime(2009, 10, 27, 20, 18, 29, tzinfo=UTC)  # Apple 10-K
JAN_2010 = datetime(2010, 1, 25, 21, 25, 58, tzinfo=UTC)  # Apple 10-K/A
OCT_2010 = datetime(2010, 10, 27, 20, 0, tzinfo=UTC)  # next 10-K repeats the restated value


def version(at: datetime, value: str) -> StoredVersion[str]:
    return StoredVersion(ref=f"{value}@{at.date()}", published_at=at, value=Decimal(value))


def test_first_value_is_a_new_version() -> None:
    assert decide_version([], OCT_2009, Decimal(4834)) == NewVersion(None)


def test_a_different_later_value_restates_the_current_version() -> None:
    original = version(OCT_2009, "4834")
    assert decide_version([original], JAN_2010, Decimal(6119)) == NewVersion(original)


def test_repeated_comparatives_are_unchanged() -> None:
    restated = version(JAN_2010, "6119")
    assert decide_version([version(OCT_2009, "4834"), restated], OCT_2010, Decimal(6119)) == (
        Unchanged(restated)
    )


def test_reading_the_original_filing_again_after_a_restatement_is_unchanged() -> None:
    original, restated = version(OCT_2009, "4834"), version(JAN_2010, "6119")
    assert decide_version([original, restated], OCT_2009, Decimal(4834)) == Unchanged(original)


def test_two_values_for_one_publication_conflict() -> None:
    decision = decide_version([version(OCT_2009, "4834")], OCT_2009, Decimal(4835))
    assert isinstance(decision, Conflict)
    assert "two values for one publication" in decision.reason


def test_a_new_value_older_than_the_newest_version_conflicts() -> None:
    decision = decide_version([version(JAN_2010, "6119")], OCT_2009, Decimal(4834))
    assert isinstance(decision, Conflict)
    assert "older than the newest" in decision.reason
