"""Scheduler process (APScheduler 3.x, in-memory job store until M0.3).

Entry point: `python -m autotrading.jobs.scheduler`. Run exactly one instance.
"""

import logging
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from autotrading.adapters.sec.refresh import REFRESH_HOUR, REFRESH_TIMEZONE
from autotrading.infra.heartbeat import HEARTBEAT_INTERVAL_SECONDS, write_heartbeat
from autotrading.infra.redis_client import make_redis
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
        CronTrigger(hour=REFRESH_HOUR, minute=0, timezone=REFRESH_TIMEZONE),
        id="sec_refresh",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
    logger.info("Scheduler started")
    scheduler.start()


if __name__ == "__main__":
    main()
