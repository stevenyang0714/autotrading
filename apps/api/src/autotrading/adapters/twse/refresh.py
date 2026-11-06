"""TWSE refresh orchestration (M3.7, ADR-039 TW5): one `twse.daily` run per scheduled slot
(07:40, 09:40 and 20:40 Singapore time, every day), or now for `make twse-refresh`. Codes held
outside the universe ride along as `extra_codes` for their closes only (M3.10, ADR-041 H6).
The first slot of each Taipei Monday fetches the company file too (M3.11, ADR-042 SC2), so a
delisting or an industry change is seen within a week; a new listing is seen the next day."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autotrading.adapters.twse.client import SOURCE_ID
from autotrading.adapters.twse.daily import TwseDailyJob
from autotrading.db.models import IngestionRun, Source
from autotrading.domain.markets import TW
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window

WEEKLY_COMPANIES_SLOT = "07:40"
IN_FLIGHT_HOURS = 6  # a run queued longer ago lost its message: nothing to wait for


def weekly_companies(slot: str, now: datetime) -> bool:
    """Whether a scheduled slot fetches the company file too: the first slot of each Taipei
    Monday."""
    return slot == WEEKLY_COMPANIES_SLOT and now.astimezone(TW.zone).isoweekday() == 1


def start_daily(
    runner: IngestionRunner,
    *,
    now: datetime,
    manual: bool,
    slot: str,
    companies: bool = False,
    extra_codes: list[str] | None = None,
) -> UUID | None:
    """The run of one slot; None when the source is disabled. A slot's run happens once a day
    (its window is the Singapore day); a manual run always runs. `companies`: fetch the
    company file too (for `make twse-rank`). `extra_codes`: listings held outside the
    universe, whose closes are stored too."""
    with runner.sessions() as session:
        source = session.get(Source, SOURCE_ID)
        if source is None or not source.enabled:
            return None
    params: dict[str, object] = {"slot": "manual" if manual else slot}
    if companies:
        params["companies"] = True
    if extra_codes:
        params["extra_codes"] = sorted(extra_codes)
    return runner.create_run(TwseDailyJob.name, params, refresh_window(now, manual=manual))


def daily_in_flight(session: Session, now: datetime) -> bool:
    """Whether a `twse.daily` run created in the last IN_FLIGHT_HOURS is queued or running: the
    Taiwan screens wait for it (M3.11, ADR-042 SC11), as the slots a sleeping Mac missed all
    fire at its wake and the screens would otherwise judge before the new session is stored."""
    count = session.scalar(
        select(func.count())
        .select_from(IngestionRun)
        .where(
            IngestionRun.job == TwseDailyJob.name,
            IngestionRun.status.in_(("queued", "running")),
            IngestionRun.created_at > now - timedelta(hours=IN_FLIGHT_HOURS),
        )
    )
    return bool(count)
