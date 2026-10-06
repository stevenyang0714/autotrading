"""Scheduler process (APScheduler 3.x, in-memory job store until M0.3).

Entry point: `python -m autotrading.jobs.scheduler`. Run exactly one instance.
"""

import logging
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from autotrading.infra.heartbeat import HEARTBEAT_INTERVAL_SECONDS, write_heartbeat
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.schedule import (
    DAILY_BARS,
    REFRESH_TIMEZONE,
    SCHEDULES,
    SNAPSHOT_SECONDS,
)
from autotrading.jobs import actors
from autotrading.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redis = make_redis(get_settings())

    def beat() -> None:
        write_heartbeat(redis, "scheduler")
        actors.heartbeat.send()

    scheduler = BlockingScheduler(timezone=UTC)
    scheduler.add_job(
        beat,
        "interval",
        seconds=HEARTBEAT_INTERVAL_SECONDS,
        id="heartbeat",
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    # SEC EDGAR (M0.5): daily at 10:00 SGT, about 22:00 ET the previous evening, when most
    # filings of that US day are in. A late start (scheduler down) still runs the same day.
    scheduler.add_job(
        lambda: actors.start_sec_refresh(manual=False),
        CronTrigger(
            hour=SCHEDULES["sec_edgar"].hour,
            minute=SCHEDULES["sec_edgar"].minute,
            timezone=REFRESH_TIMEZONE,
        ),
        id="sec_refresh",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # FRED / ALFRED (M0.6): daily at 10:15 SGT, after SEC.
    scheduler.add_job(
        lambda: actors.start_fred_refresh(manual=False),
        CronTrigger(
            hour=SCHEDULES["fred"].hour,
            minute=SCHEDULES["fred"].minute,
            timezone=REFRESH_TIMEZONE,
        ),
        id="fred_refresh",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # Alpaca (M0.7): snapshots each minute (the job checks US market hours itself) and daily
    # SIP bars after the close.
    scheduler.add_job(
        lambda: actors.start_alpaca_snapshots(),
        "interval",
        seconds=SNAPSHOT_SECONDS,
        id="alpaca_snapshots",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: actors.start_alpaca_daily_bars(manual=False),
        CronTrigger(hour=DAILY_BARS.hour, minute=DAILY_BARS.minute, timezone=REFRESH_TIMEZONE),
        id="alpaca_daily_bars",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
    logger.info("Scheduler started")
    scheduler.start()


if __name__ == "__main__":
    main()
