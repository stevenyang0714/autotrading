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
    BACKTESTS,
    BUYBACK_STATES,
    DAILY_BARS,
    DELIVERY,
    FACTORS,
    FINMIND,
    FRED,
    GDELT,
    MOMENTUM,
    NEWS_FEEDS,
    PORTFOLIO,
    REFRESH_TIMEZONE,
    REGIME,
    ROTATION,
    SEC_EDGAR,
    SNAPSHOT_SECONDS,
    TW_FACTORS,
    TWSE,
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
    if not get_settings().scheduled_ingestion:
        logger.info("Scheduled ingestion is off (SCHEDULED_INGESTION=false): heartbeat only")
        signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
        scheduler.start()
        return
    # SEC EDGAR (M0.5): daily at 10:00 SGT, about 22:00 ET the previous evening, when most
    # filings of that US day are in. A late start (scheduler down) still runs the same day.
    scheduler.add_job(
        lambda: actors.start_sec_refresh(manual=False),
        CronTrigger(
            hour=SEC_EDGAR.hour,
            minute=SEC_EDGAR.minute,
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
            hour=FRED.hour,
            minute=FRED.minute,
            timezone=REFRESH_TIMEZONE,
        ),
        id="fred_refresh",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # Macro regime (M2.1): daily at 10:55 SGT, after FRED and the daily closes.
    scheduler.add_job(
        lambda: actors.start_regime_evaluation(manual=False),
        CronTrigger(hour=REGIME.hour, minute=REGIME.minute, timezone=REFRESH_TIMEZONE),
        id="regime",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # Factor snapshots (M2.2): daily at 11:05 SGT, after the closes, dividends and SEC.
    scheduler.add_job(
        lambda: actors.start_factor_evaluation(manual=False),
        CronTrigger(hour=FACTORS.hour, minute=FACTORS.minute, timezone=REFRESH_TIMEZONE),
        id="factors",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # Paper portfolio (M2.3): daily at 11:10 SGT, with its drawdown alert.
    scheduler.add_job(
        lambda: actors.start_portfolio_snapshot(manual=False),
        CronTrigger(hour=PORTFOLIO.hour, minute=PORTFOLIO.minute, timezone=REFRESH_TIMEZONE),
        id="portfolio",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # Backtests (M2.5): checked daily at 11:20 SGT, run once a month (after the rotation).
    scheduler.add_job(
        lambda: actors.start_backtests(manual=False),
        CronTrigger(hour=BACKTESTS.hour, minute=BACKTESTS.minute, timezone=REFRESH_TIMEZONE),
        id="backtests",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # S3 ETF rotation (M2.4): daily at 11:15 SGT, after the regime and the factor snapshots.
    scheduler.add_job(
        lambda: actors.start_rotation_evaluation(manual=False),
        CronTrigger(hour=ROTATION.hour, minute=ROTATION.minute, timezone=REFRESH_TIMEZONE),
        id="rotation",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # TWSE OpenAPI (M3.7, ADR-039 TW5): three slots a day, weekends too; each slot's run once.
    for hour, minute in TWSE.times:
        slot = f"{hour:02d}:{minute:02d}"
        scheduler.add_job(
            lambda slot=slot: actors.start_twse_refresh(manual=False, slot=slot),
            CronTrigger(hour=hour, minute=minute, timezone=REFRESH_TIMEZONE),
            id=f"twse_refresh_{hour:02d}{minute:02d}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=12 * 3600,
        )
    # FinMind (M3.7b, ADR-040 TW25): the Taiwan flows and foreign holdings, daily at 21:30 SGT.
    scheduler.add_job(
        lambda: actors.start_finmind_refresh(manual=False),
        CronTrigger(hour=FINMIND.hour, minute=FINMIND.minute, timezone=REFRESH_TIMEZONE),
        id="finmind_flows",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # Taiwan factor snapshots (M3.7, ADR-039 TW10): daily at 09:50 SGT, after the TWSE runs.
    scheduler.add_job(
        lambda: actors.start_taiwan_factor_evaluation(manual=False),
        CronTrigger(hour=TW_FACTORS.hour, minute=TW_FACTORS.minute, timezone=REFRESH_TIMEZONE),
        id="taiwan_factors",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # S4 momentum (M3.0, ADR-036 D7): daily at 11:17 SGT, after the factor snapshots.
    scheduler.add_job(
        lambda: actors.start_momentum_evaluation(manual=False),
        CronTrigger(hour=MOMENTUM.hour, minute=MOMENTUM.minute, timezone=REFRESH_TIMEZONE),
        id="momentum",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 3600,
    )
    # Buyback states (M1.4b): daily at 11:00 SGT, after the SEC and FRED refreshes.
    scheduler.add_job(
        lambda: actors.start_buyback_evaluation(manual=False),
        CronTrigger(
            hour=BUYBACK_STATES.hour,
            minute=BUYBACK_STATES.minute,
            timezone=REFRESH_TIMEZONE,
        ),
        id="buyback_states",
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
    # News (M0.8): GDELT hourly, official feeds every 30 minutes (ingestion/schedule.py).
    assert GDELT.minutes == 60  # one cron minute per hour
    scheduler.add_job(
        lambda: actors.start_news_gdelt(manual=False),
        CronTrigger(minute=GDELT.offset, timezone=UTC),
        id="news_gdelt",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        lambda: actors.start_news_feeds(manual=False),
        CronTrigger(
            minute=f"{NEWS_FEEDS.offset},{NEWS_FEEDS.offset + NEWS_FEEDS.minutes}",
            timezone=UTC,
        ),
        id="news_feeds",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=900,
    )
    # Alert delivery (M3.0b, ADR-037): every 5 minutes; does nothing until Telegram is set up.
    scheduler.add_job(
        lambda: actors.start_alert_delivery(manual=False),
        CronTrigger(minute=f"{DELIVERY.offset}-59/{DELIVERY.minutes}", timezone=UTC),
        id="alert_delivery",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=240,
    )
    # The weekly digest (M3.0c, ADR-038): checked at the top of every hour (Singapore time);
    # the delivery rules decide the weekday and hour (Monday 08:00), sent once a week.
    scheduler.add_job(
        lambda: actors.start_digest(manual=False),
        CronTrigger(minute=0, timezone=REFRESH_TIMEZONE),
        id="weekly_digest",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )
    signal.signal(signal.SIGTERM, lambda *_: scheduler.shutdown(wait=False))
    logger.info("Scheduler started")
    scheduler.start()


if __name__ == "__main__":
    main()
