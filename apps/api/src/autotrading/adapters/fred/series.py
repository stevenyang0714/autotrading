"""Job `fred.series` (M0.6): one FRED series, its metadata and every ALFRED vintage.

fetch: the series record, its vintage dates, then all observations over the full real-time
       range (1776-07-04 .. 9999-12-31). FRED serves at most 2,000 vintage dates per request,
       so series with more (daily market series have 3,000-5,000) are read in real-time windows
       of at most 1,900 vintages; a value spanning two windows comes back once per window, and
       the repeat is "unchanged" under the version rules. Each request pages by 100,000 rows.
store: refresh the series metadata in macro_series; write each (date, vintage, value) as a
       version in macro_observations, published at the end of the vintage's first day in New
       York (ADR-012, ADR-015). Missing values (".") are skipped.
"""

import json
import logging
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, cast

from autotrading.adapters.fred.client import FredClient
from autotrading.db.models import MacroSeries, Source
from autotrading.domain.macro import Frequency, MacroObservationIn, period_end
from autotrading.domain.provenance import LicenseStatus, Provenance, end_of_day
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoredPayload,
    StoreResult,
    register_job,
)
from autotrading.repositories.audit import set_actor
from autotrading.repositories.macro import MacroObservationRepository

logger = logging.getLogger(__name__)

SOURCE_ID = "fred"
ACTOR = f"ingest:{SOURCE_ID}"
REALTIME_MIN, REALTIME_MAX = "1776-07-04", "9999-12-31"
PAGE_SIZE = 100_000
VINTAGE_PAGE_SIZE = 10_000
MAX_VINTAGES_PER_REQUEST = 1_900  # FRED's limit is 2,000; margin for a vintage added meanwhile
SOURCE_TIMEZONE = "America/New_York"


def series_page(series_id: str) -> str:
    """Public FRED page of the series: what stored values link to (never the API URL)."""
    return f"https://fred.stlouisfed.org/series/{series_id}"


def realtime_windows(
    vintages: list[str], size: int = MAX_VINTAGES_PER_REQUEST
) -> list[tuple[str, str]]:
    """Real-time windows covering every vintage, each with at most `size` vintage dates."""
    if len(vintages) <= size:
        return [(REALTIME_MIN, REALTIME_MAX)]
    groups = [vintages[i : i + size] for i in range(0, len(vintages), size)]
    starts = [REALTIME_MIN] + [group[0] for group in groups[1:]]
    ends = [group[-1] for group in groups[:-1]] + [REALTIME_MAX]
    return list(zip(starts, ends, strict=True))


def observation_params(
    series_id: str, window: tuple[str, str], offset: int, observation_start: str | None
) -> dict[str, str]:
    params = {
        "series_id": series_id,
        "realtime_start": window[0],
        "realtime_end": window[1],
        "limit": str(PAGE_SIZE),
        "offset": str(offset),
    }
    if observation_start:
        params["observation_start"] = observation_start
    return params


def payload_kind(url: str) -> str:
    """'series', 'vintagedates' or 'observations', from the public request URL."""
    path = url.split("?", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1]


def midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=UTC)


def parse_last_updated(value: str | None) -> datetime | None:
    """FRED's "2026-09-11 07:38:03-05" (Central time offset) as an aware datetime."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace(" ", "T") + (":00" if value[-3] in "+-" else ""))


def parse_value(raw: str) -> Decimal | None:
    if raw.strip() == ".":
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


@register_job
class FredSeriesJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "fred.series"

    def client(self) -> FredClient:
        return FredClient.from_settings()

    @property
    def series_id(self) -> str:
        return str(self.params["series_id"]).upper()

    @property
    def observation_start(self) -> str | None:
        """Optional lower bound on observation dates (recorded test fixtures use it)."""
        value = self.params.get("observation_start")
        return str(value) if value else None

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        sid = self.series_id
        with self.client() as client:
            payloads = [client.get("series", {"series_id": sid}, ctx.acquire)]
            vintages: list[str] = []
            while True:
                page = client.get(
                    "series/vintagedates",
                    {
                        "series_id": sid,
                        "limit": str(VINTAGE_PAGE_SIZE),
                        "offset": str(len(vintages)),
                    },
                    ctx.acquire,
                )
                payloads.append(page)
                data = json.loads(page.content)
                vintages.extend(data["vintage_dates"])
                if not data["vintage_dates"] or len(vintages) >= int(data["count"]):
                    break
            for window in realtime_windows(vintages):
                offset = 0
                while True:
                    params = observation_params(sid, window, offset, self.observation_start)
                    page = client.get("series/observations", params, ctx.acquire)
                    payloads.append(page)
                    data = json.loads(page.content)
                    offset += len(data["observations"])
                    if not data["observations"] or offset >= int(data["count"]):
                        break
        return payloads

    def store(self, ctx: StoreContext) -> StoreResult:
        session = ctx.session
        set_actor(session, ACTOR)
        series = session.get(MacroSeries, self.series_id)
        if series is None:
            raise LookupError(
                f"{self.series_id} is not in macro_series; add it to config/macro_series.yaml "
                "and run make migrate"
            )
        source = session.get_one(Source, SOURCE_ID)
        by_kind: dict[str, list[StoredPayload]] = {}
        for payload in ctx.payloads:
            by_kind.setdefault(payload_kind(payload.source_url), []).append(payload)
        (meta_payload,) = by_kind["series"]
        pages = by_kind.get("observations", [])
        changed = _update_metadata(series, json.loads(meta_payload.content)["seriess"][0])
        frequency = cast(Frequency, series.frequency_short or "D")

        observations: list[MacroObservationIn] = []
        missing = 0
        for page in pages:
            for row in json.loads(page.content)["observations"]:
                value = parse_value(row["value"])
                if value is None:
                    missing += 1
                    continue
                observations.append(
                    _observation(self.series_id, row, value, frequency, page, source, ctx)
                )
        if missing:
            logger.info('FRED %s: %d missing values (".") skipped', self.series_id, missing)
        result = MacroObservationRepository(session).insert_many(observations, actor=ACTOR)
        for conflict in result.conflicts:
            logger.warning("FRED %s conflicting value not stored: %s", self.series_id, conflict)
        return StoreResult(
            inserted=result.inserted + changed,
            unchanged=result.unchanged + (not changed),
            conflicted=len(result.conflicts),
        )


def _update_metadata(series: MacroSeries, meta: dict[str, Any]) -> int:
    """Copy FRED's series record into the registry row; 1 if anything changed."""
    wanted = {
        "title": meta.get("title"),
        "units": meta.get("units"),
        "units_short": meta.get("units_short"),
        "frequency": meta.get("frequency"),
        "frequency_short": meta.get("frequency_short"),
        "seasonal_adjustment_short": meta.get("seasonal_adjustment_short"),
        "last_updated": parse_last_updated(meta.get("last_updated")),
    }
    changed = {k: v for k, v in wanted.items() if getattr(series, k) != v}
    for key, value in changed.items():
        setattr(series, key, value)
    return int(bool(changed))


def _observation(
    series_id: str,
    row: dict[str, str],
    value: Decimal,
    frequency: Frequency,
    page: StoredPayload,
    source: Source,
    ctx: StoreContext,
) -> MacroObservationIn:
    observed = date.fromisoformat(row["date"])
    vintage = date.fromisoformat(row["realtime_start"])
    ends = midnight_utc(period_end(observed, frequency))
    return MacroObservationIn(
        series_id=series_id,
        observation_date=observed,
        value=value,
        vintage=vintage,
        provenance=Provenance(
            source_id=source.id,
            source_tier=source.tier,
            source_url=series_page(series_id),
            published_at=end_of_day(vintage),
            published_at_precision="day",
            ingested_at=page.fetched_at,
            effective_from=midnight_utc(observed),
            effective_to=ends,
            as_of=ends,
            # The sources table's CHECK constraint limits it to the LicenseStatus values.
            license_status=cast(LicenseStatus, source.license_status),
            confidence=1.0,
            source_timezone=SOURCE_TIMEZONE,
            ingestion_run_id=ctx.run_id,
            raw_payload_sha256=page.sha256,
        ),
    )
