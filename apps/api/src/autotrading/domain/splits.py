"""Stock splits and per-share history (M1.1, ADR-021). Pure functions; no I/O.

Companies restate per-share values and share counts for a split in every filing issued after
it (ASC 260), so a reported value is on the basis of the splits effective before its filing was
accepted. To compare values across a split, each one is moved to the basis of a chosen time T
(usually the As known on time): multiplied (share counts) or divided (per-share amounts) by
every split effective after its filing and up to T. Reported values stay as reported; the
adjusted value is shown beside them.

A split is effective from the start of its ex-date in New York. Splits not yet effective at T
never adjust anything, so an As known on view before a split shows no adjustment.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
PER_SHARE_METRICS = frozenset({"eps_diluted", "eps_basic", "close"})  # close: a daily close
SHARE_COUNT_METRICS = frozenset(
    {
        "diluted_shares",
        "basic_shares",
        "shares_outstanding",
        "shares_outstanding_cover",
        "shares_repurchased",
        "volume",  # shares traded in a day (M1.5 reaction volume)
    }
)
ADJUSTED_METRICS = PER_SHARE_METRICS | SHARE_COUNT_METRICS
# Restatement ratios that look like a split when no recorded split explains them.
SPLIT_LIKE = tuple(Fraction(k) for k in (Fraction(3, 2), 2, 3, 4, 5, 7, 8, 10, 15, 20))
SPLIT_LIKE_TOLERANCE = Fraction(2, 100)


def effective_at(ex_date: date) -> datetime:
    """Start of the ex-date in New York: the first session on the new basis."""
    return datetime.combine(ex_date, time(0, 0), tzinfo=NEW_YORK).astimezone(UTC)


@dataclass(frozen=True)
class Split:
    ex_date: date
    old_rate: Decimal
    new_rate: Decimal

    @property
    def ratio(self) -> Fraction:
        """Shares after per share before: 4 for a 4-for-1 split."""
        return Fraction(self.new_rate) / Fraction(self.old_rate)

    @property
    def effective_at(self) -> datetime:
        return effective_at(self.ex_date)


@dataclass(frozen=True)
class Adjusted:
    value: Decimal
    factor: Fraction  # product of the ratios applied
    splits: tuple[Split, ...]


def splits_between(
    splits: Iterable[Split], reported_at: datetime, basis_at: datetime
) -> list[Split]:
    """Splits effective after a value was reported and no later than the basis time."""
    return sorted(
        (s for s in splits if reported_at < s.effective_at <= basis_at), key=lambda s: s.ex_date
    )


def adjust(
    metric_id: str,
    value: Decimal,
    reported_at: datetime,
    basis_at: datetime,
    splits: Iterable[Split],
) -> Adjusted | None:
    """The value on the basis of `basis_at`, or None when no split applies (or the metric is
    not per-share or a share count)."""
    if metric_id not in ADJUSTED_METRICS:
        return None
    used = splits_between(splits, reported_at, basis_at)
    if not used:
        return None
    factor = Fraction(1)
    for split in used:
        factor *= split.ratio
    exact = Fraction(value) / factor if metric_id in PER_SHARE_METRICS else Fraction(value) * factor
    quantum = Decimal("0.000001") if metric_id in PER_SHARE_METRICS else Decimal(1)
    adjusted = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(quantum)
    return Adjusted(adjusted.normalize() if adjusted else adjusted, factor, tuple(used))


@dataclass(frozen=True)
class ReportedVersion:
    metric_id: str
    period_start: date | None
    period_end: date
    value: Decimal
    reported_at: datetime
    accession: str | None


def _close(a: Fraction, b: Fraction, metric_id: str) -> bool:
    if metric_id in PER_SHARE_METRICS:  # reported in cents
        return abs(a - b) <= max(Fraction(11, 1000), abs(b) / 200)
    return abs(a - b) <= abs(b) / 200  # share counts are rounded to thousands or millions


def _split_like(ratio: Fraction) -> Fraction | None:
    for k in SPLIT_LIKE:
        for candidate in (k, 1 / k):
            if abs(ratio - candidate) <= candidate * SPLIT_LIKE_TOLERANCE:
                return candidate
    return None


def unexplained_splits(versions: Iterable[ReportedVersion], splits: Sequence[Split]) -> list[str]:
    """Restatements that look like a split no recorded split explains.

    A split restates per-share amounts and share counts of a period together, in opposite
    directions: diluted EPS divided by k and diluted shares multiplied by k in the same later
    filing. Only that pattern is flagged; an EPS restatement alone (Apple's 2010 revenue
    recognition change moved Q3 FY2009 EPS from 1.35 to 2.01) is an ordinary restatement.
    """
    ratios: dict[
        tuple[str, date | None, date, str | None], tuple[Fraction, ReportedVersion, ReportedVersion]
    ] = {}
    groups: dict[tuple[str, date | None, date], list[ReportedVersion]] = defaultdict(list)
    for version in versions:
        if version.metric_id in ("eps_diluted", "diluted_shares"):
            groups[(version.metric_id, version.period_start, version.period_end)].append(version)
    for (metric_id, start, end), group in groups.items():
        group.sort(key=lambda v: v.reported_at)
        for older, newer in pairwise(group):
            moved = adjust(metric_id, older.value, older.reported_at, newer.reported_at, splits)
            old = Fraction(moved.value if moved else older.value)
            new = Fraction(newer.value)
            if new == 0 or old == 0 or _close(old, new, metric_id):
                continue
            # shares after per share before: EPS old/new, shares new/old
            ratio = old / new if metric_id in PER_SHARE_METRICS else new / old
            ratios[(metric_id, start, end, newer.accession)] = (ratio, older, newer)
    findings = []
    for (metric_id, start, end, accession), (ratio, older, newer) in sorted(
        ratios.items(), key=lambda kv: str(kv[0])
    ):
        if metric_id != "eps_diluted":
            continue
        shares = ratios.get(("diluted_shares", start, end, accession))
        k = _split_like(ratio)
        if k is None or shares is None or _split_like(shares[0]) != k:
            continue
        findings.append(
            f"{end}: diluted EPS {older.value} ({older.accession}) became {newer.value} "
            f"({newer.accession}) and diluted shares moved by the same ratio of about "
            f"{float(k):g}, with no recorded split between them"
        )
    return findings
