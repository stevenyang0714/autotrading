"""Dramatiq actors.

Worker entry point: `dramatiq autotrading.jobs.actors --processes 1 --threads 2`.
Importing this module loads settings (enforcing the live-trading guard, ADR-008)
and configures the broker before any actor is declared.
"""

import logging
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any, cast
from uuid import UUID

import dramatiq
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from autotrading import adapters  # noqa: F401  (adapters register their ingestion jobs)
from autotrading.adapters.alpaca import refresh as alpaca_refresh
from autotrading.adapters.finmind import refresh as finmind_refresh
from autotrading.adapters.fred import refresh as fred_refresh
from autotrading.adapters.news import refresh as news_refresh
from autotrading.adapters.sec import refresh as sec_refresh
from autotrading.adapters.telegram import client as telegram
from autotrading.adapters.twse import refresh as twse_refresh
from autotrading.api import buyback_states
from autotrading.domain.fair_value import month_ends
from autotrading.domain.markets import Market
from autotrading.infra.db import make_background_engine
from autotrading.infra.heartbeat import write_heartbeat
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.actors import INGESTION_QUEUE, declare_ingestion_actor
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import market_calendar
from autotrading.jobs.broker import WorkerHeartbeat, configure_broker
from autotrading.repositories import (
    backtest,
    delivery,
    factors,
    holdings,
    momentum,
    regime,
    risk,
    rotation,
)
from autotrading.settings import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()
broker = configure_broker(_settings)
_redis = make_redis(_settings)
broker.add_middleware(WorkerHeartbeat(lambda: write_heartbeat(_redis, "worker")))


@dramatiq.actor(queue_name="system", max_retries=0, time_limit=10_000, broker=broker)
def heartbeat() -> None:
    """Prove the scheduler -> queue -> worker path. Enqueued by the scheduler."""
    write_heartbeat(_redis, "queue")


@lru_cache
def ingestion_runner() -> IngestionRunner:
    """Created on first use inside the worker, so importing this module stays cheap."""
    return IngestionRunner(
        sessions(),
        RawPayloadStore(make_s3_client(_settings), _settings.s3_bucket),
        TokenBucketLimiter(_redis),
    )


run_ingestion = declare_ingestion_actor(
    broker,
    ingestion_runner,
    max_retries=_settings.ingestion_max_retries,
    min_backoff_ms=_settings.ingestion_min_backoff_ms,
    max_backoff_ms=_settings.ingestion_max_backoff_ms,
)


# ---------- SEC EDGAR refresh (M0.5) ----------


@dramatiq.actor(queue_name=INGESTION_QUEUE, max_retries=3, broker=broker)
def enqueue_sec_companies(message_data: dict[str, Any], result: str) -> None:
    """on_success callback of the `sec.tickers` run: fan out one run per company."""
    tickers_run = UUID(message_data["args"][0])
    run_ids = sec_refresh.create_company_runs(ingestion_runner(), tickers_run)
    for run_id in run_ids:
        run_ingestion.send_with_options(args=(str(run_id),), on_success=enqueue_sec_filing_xbrl)
    logger.info("SEC refresh: %d company runs queued after tickers run %s", len(run_ids), result)


@dramatiq.actor(queue_name=INGESTION_QUEUE, max_retries=3, broker=broker)
def enqueue_sec_filing_xbrl(message_data: dict[str, Any], result: str) -> None:
    """on_success callback of a `sec.company` run: read new filings' own XBRL (M1.1), new
    8-Ks for buyback announcements (M1.4a) and new earnings releases for guidance (M1.5)."""
    company_run = UUID(message_data["args"][0])
    runner = ingestion_runner()
    for kind, run_id in (
        ("filing XBRL", sec_refresh.create_filing_xbrl_run(runner, company_run)),
        ("8-K", sec_refresh.create_eight_k_run(runner, company_run)),
        ("earnings release", sec_refresh.create_earnings_run(runner, company_run)),
    ):
        if run_id is not None:
            run_ingestion.send(str(run_id))
            logger.info("SEC refresh: %s run %s queued after %s", kind, run_id, result)


def start_sec_refresh(*, manual: bool) -> UUID | None:
    """Queue a refresh: the tickers run first, the company runs once it succeeds."""
    run_id = sec_refresh.start_refresh(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual,
        config_dir=_settings.resolved_config_dir(),
    )
    if run_id is None:
        logger.info("SEC refresh skipped: source sec_edgar is not enabled")
        return None
    run_ingestion.send_with_options(args=(str(run_id),), on_success=enqueue_sec_companies)
    return run_id


# ---------- FRED / ALFRED refresh (M0.6) ----------


def start_fred_refresh(*, manual: bool) -> list[UUID]:
    """Queue one run per enabled macro series; empty when the source is not enabled."""
    run_ids = fred_refresh.start_refresh(ingestion_runner(), now=datetime.now(UTC), manual=manual)
    if not run_ids:
        logger.info("FRED refresh skipped: source fred is not enabled or no series is enabled")
    for run_id in run_ids:
        run_ingestion.send(str(run_id))
    return run_ids


# ---------- TWSE OpenAPI (M3.7) ----------


def start_twse_refresh(
    *, manual: bool, slot: str = "manual", companies: bool = False
) -> UUID | None:
    """Queue the Taiwan universe's latest session (ADR-039 TW5), with the codes held outside it
    (ADR-041 H6); None when twse_openapi is not enabled."""
    with sessions()() as session:
        extra, _ = holdings.tracked(session, "TW")
    now = datetime.now(UTC)
    run_id = twse_refresh.start_daily(
        ingestion_runner(),
        now=now,
        manual=manual,
        slot=slot,
        companies=companies or (not manual and twse_refresh.weekly_companies(slot, now)),
        extra_codes=extra,
    )
    if run_id is None:
        logger.info("TWSE refresh skipped: twse_openapi is not enabled")
    else:
        run_ingestion.send(str(run_id))
    return run_id


# ---------- FinMind (M3.7b) ----------


def start_finmind_refresh(*, manual: bool) -> UUID | None:
    """Queue the Taiwan universe's institutional flows and foreign holdings of the last days
    (ADR-040 TW25); None when finmind is not enabled."""
    from autotrading.domain.markets import TW
    from autotrading.ingestion.schedule import market_calendar
    from autotrading.repositories.universe import taiwan_universe

    run_id = finmind_refresh.start_flows(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual,
        universe=taiwan_universe(),
        calendar=market_calendar(TW.exchange),
    )
    if run_id is None:
        logger.info("FinMind refresh skipped: finmind is not enabled")
        return None
    run_ingestion.send(str(run_id))
    start_candidate_flows(manual=manual)
    return run_id


CANDIDATE_SPACING_MS = 270_000  # a candidates' run (20 requests at 12.5 s) after the one before


def start_candidate_flows(*, manual: bool) -> int:
    """The institutional flows of the Taiwan screens' candidates (ADR-042 SC5), after the
    universe's run; each run sent when the one before should be done (KI-30)."""
    from autotrading.repositories import screens
    from autotrading.repositories.universe import taiwan_universe

    universe = taiwan_universe()
    with sessions()() as session:
        rules = screens.stored_screen_rules(session)
        codes = screens.candidates(session, rules, universe.codes) if rules else []
    run_ids = finmind_refresh.start_candidate_flows(
        ingestion_runner(), now=datetime.now(UTC), manual=manual, codes=codes
    )
    for i, run_id in enumerate(run_ids, start=1):
        run_ingestion.send_with_options(args=(str(run_id),), delay=i * CANDIDATE_SPACING_MS)
    return len(run_ids)


def start_finmind_backfill(end: date | None = None) -> int:
    """Queue the one-time history: one run per code and dataset since 2016, up to `end`
    (default: the day before the first TWSE session, 2026-10-20)."""
    from autotrading.repositories.universe import taiwan_universe

    run_ids = finmind_refresh.start_history(
        ingestion_runner(),
        now=datetime.now(UTC),
        universe=taiwan_universe(),
        end=end or date(2026, 10, 20),
    )
    for run_id in run_ids:
        run_ingestion.send(str(run_id))
    return len(run_ids)


LISTED_SPACING_MS = 13_000  # one FinMind request every 13 s: under the 300-an-hour cap


def start_finmind_listed_backfill(datasets: tuple[str, ...] | None = None) -> int:
    """Queue the listed companies' history (ADR-042 SC4): one run per code and dataset, each
    sent 13 s after the one before, so the worker never holds more than one waiting FinMind run
    (KI-30); runs that have succeeded are not queued again."""
    from autotrading.domain.markets import TW
    from autotrading.repositories.universe import taiwan_universe

    run_ids = finmind_refresh.start_listed_history(
        ingestion_runner(),
        universe=taiwan_universe(),
        today=datetime.now(UTC).astimezone(TW.zone).date(),
        datasets=datasets or finmind_refresh.LISTED_DATASETS,
    )
    for i, run_id in enumerate(run_ids):
        run_ingestion.send_with_options(args=(str(run_id),), delay=i * LISTED_SPACING_MS)
    return len(run_ids)


# ---------- Alpaca market data (M0.7) ----------


def start_alpaca_snapshots(*, force: bool = False) -> UUID | None:
    """Queue this minute's snapshot run during US market hours (or now, when forced)."""
    run_id = alpaca_refresh.start_snapshots(
        ingestion_runner(),
        now=datetime.now(UTC),
        calendar=market_calendar(),
        config_dir=_settings.resolved_config_dir(),
        force=force,
    )
    if run_id is not None:
        run_ingestion.send(str(run_id))
    return run_id


def start_alpaca_daily_bars(*, manual: bool, backfill: bool = False) -> UUID | None:
    run_id = alpaca_refresh.start_daily_bars(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual,
        config_dir=_settings.resolved_config_dir(),
        backfill=backfill,
    )
    if run_id is None:
        logger.info("Alpaca bars skipped: alpaca_iex is not enabled or has no keys")
    else:
        run_ingestion.send(str(run_id))
    splits_run = alpaca_refresh.start_splits(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual or backfill,
        config_dir=_settings.resolved_config_dir(),
    )
    if splits_run is not None:
        run_ingestion.send(str(splits_run))
    dividends_run = alpaca_refresh.start_dividends(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual or backfill,
        config_dir=_settings.resolved_config_dir(),
    )
    if dividends_run is not None:
        run_ingestion.send(str(dividends_run))
    with sessions()() as session:
        tracked, since = holdings.tracked(session, "US")
    for tracked_run in alpaca_refresh.start_tracked(
        ingestion_runner(),
        now=datetime.now(UTC),
        manual=manual or backfill,
        symbols=tracked,
        since=since,
    ):
        run_ingestion.send(str(tracked_run))
    return run_id


# ---------- news (M0.8) ----------


def start_news_gdelt(*, manual: bool) -> UUID | None:
    """Queue this hour's GDELT run (or one now, when manual)."""
    run_id = news_refresh.start_gdelt(ingestion_runner(), now=datetime.now(UTC), manual=manual)
    if run_id is None:
        logger.info("GDELT skipped: the gdelt source is not enabled")
    else:
        run_ingestion.send(str(run_id))
    return run_id


def start_news_gdelt_backfill() -> list[UUID]:
    run_ids = news_refresh.start_gdelt_backfill(ingestion_runner(), now=datetime.now(UTC))
    for run_id in run_ids:
        run_ingestion.send(str(run_id))
    return run_ids


def start_news_feeds(*, manual: bool) -> list[UUID]:
    """Queue one run per enabled RSS / Atom feed."""
    run_ids = news_refresh.start_feeds(ingestion_runner(), now=datetime.now(UTC), manual=manual)
    for run_id in run_ids:
        run_ingestion.send(str(run_id))
    return run_ids


# ---------- buyback states (M1.4b) ----------

EVALUATION_QUEUE = "evaluation"


@lru_cache
def sessions() -> sessionmaker[Session]:
    """One engine, so one connection pool, for every job in this process (worker or
    scheduler)."""
    return sessionmaker(make_background_engine(_settings))


def _now(session: Session) -> datetime:
    return session.execute(select(func.now())).scalar_one()


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def evaluate_buyback_states(trigger: str) -> None:
    """Every universe equity now (T = system time = now), under the active rule set."""
    with sessions()() as session:
        now = _now(session)
        stored = buyback_states.evaluate_universe(session, now, now, trigger)  # type: ignore[arg-type]
    logger.info("Buyback states: %d assignments stored at %s (%s)", stored, now, trigger)


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def backfill_buyback_states(known_at: str, system_time: str) -> None:
    """Every universe equity at one month end, as the database held it at `system_time`."""
    at, held = datetime.fromisoformat(known_at), datetime.fromisoformat(system_time)
    with sessions()() as session:
        stored = buyback_states.evaluate_universe(session, at, held, "backfill")
    logger.info("Buyback states backfill: %d assignments stored for %s", stored, at)


def start_buyback_evaluation(*, manual: bool) -> None:
    evaluate_buyback_states.send("manual" if manual else "schedule")


# ---------- macro regime (M2.1) ----------

REGIME_BACKFILL_SINCE = date(2016, 1, 1)  # ADR-029 R3: ETF closes start in 2016
REGIME_CALENDAR = "SPY"  # every session SPY closed, plus month ends (ADR-036 D5)


def _record_regime(at: datetime, held: datetime, trigger: str) -> None:
    with sessions()() as session:
        rules = regime.stored_regime_rules(session)
        if rules is None:
            logger.warning("Regime rules not loaded (make migrate): nothing assessed")
            return
        stored = regime.record_regime(session, rules, at, held, trigger)
        session.commit()
    logger.info("Regime at %s (%s): %s", at, trigger, "stored" if stored else "already stored")


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def evaluate_regime(trigger: str) -> None:
    """The regime now (T = system time = now) under the active rule set."""
    with sessions()() as session:
        now = _now(session)
    _record_regime(now, now, trigger)


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def backfill_regime(known_at: str, system_time: str) -> None:
    """The regime at one session close or month end, as the database held it at
    `system_time`. Its stress alerts come from `make alerts-backfill`, which pairs the stored
    assessments in order (messages run concurrently)."""
    _record_regime(
        datetime.fromisoformat(known_at), datetime.fromisoformat(system_time), "backfill"
    )


def start_regime_evaluation(*, manual: bool) -> None:
    evaluate_regime.send("manual" if manual else "schedule")


def start_regime_backfill() -> int:
    """One message per session close and month end since 2016 (ADR-036 D5; month ends only
    under 0.1.0), all with one system time (now)."""
    with sessions()() as session:
        now = _now(session)
        points = factors.session_points(session, REGIME_CALENDAR, REGIME_BACKFILL_SINCE, now)
    for point in points:
        backfill_regime.send(point.isoformat(), now.isoformat())
    return len(points)


# ---------- price, trend and factors (M2.2) ----------

FACTORS_BACKFILL_SINCE = 2016  # ADR-030 F2: closes and dividends start in 2016
FACTORS_TIME_LIMIT_MS = 60 * 60 * 1000  # a year of sessions for 18 instruments


@dramatiq.actor(
    queue_name=EVALUATION_QUEUE, max_retries=1, time_limit=FACTORS_TIME_LIMIT_MS, broker=broker
)
def evaluate_factors(trigger: str) -> None:
    """Every universe instrument's snapshot now (T = system time = now), all measures."""
    with sessions()() as session:
        now = _now(session)
        definitions = factors.stored_definitions(session)
        if definitions is None:
            logger.warning("Factor definitions not loaded (make migrate): nothing computed")
            return
        stored = factors.record_universe(session, definitions, [(now, "all")], now, trigger)
    logger.info("Factor snapshots at %s (%s): %d stored", now, trigger, stored)


@dramatiq.actor(
    queue_name=EVALUATION_QUEUE, max_retries=1, time_limit=FACTORS_TIME_LIMIT_MS, broker=broker
)
def backfill_factors(year: int, system_time: str, market: str = "US") -> None:
    """One year of snapshots (every session, all measures at month ends), as the database held
    them at `system_time`, under the market's active definitions (TW since M3.7b)."""
    held = datetime.fromisoformat(system_time)
    with sessions()() as session:
        definitions = factors.stored_definitions(
            session, factors.active_factor_version(cast(Market, market))
        )
        if definitions is None:
            logger.warning("Factor definitions not loaded (make migrate): nothing computed")
            return
        points = factors.backfill_points(session, definitions, year, held)
        stored = factors.record_universe(session, definitions, points, held, "backfill")
    logger.info("Factor backfill %d: %d points, %d snapshots stored", year, len(points), stored)


def start_factor_evaluation(*, manual: bool) -> None:
    evaluate_factors.send("manual" if manual else "schedule")


@dramatiq.actor(
    queue_name=EVALUATION_QUEUE, max_retries=1, time_limit=FACTORS_TIME_LIMIT_MS, broker=broker
)
def evaluate_taiwan_factors(trigger: str) -> None:
    """Every Taiwan universe instrument's snapshot now under the active Taiwan definitions
    (M3.7, ADR-039 TW10): price measures against 0050 on Taipei dates. No backfill."""
    with sessions()() as session:
        now = _now(session)
        definitions = factors.stored_definitions(session, factors.active_factor_version("TW"))
        if definitions is None:
            logger.warning("Taiwan factor definitions not loaded (make migrate): nothing computed")
            return
        stored = factors.record_universe(session, definitions, [(now, "all")], now, trigger)
    logger.info("Taiwan factor snapshots at %s (%s): %d stored", now, trigger, stored)


def start_taiwan_factor_evaluation(*, manual: bool) -> None:
    evaluate_taiwan_factors.send("manual" if manual else "schedule")


def start_factor_backfill(market: str = "US") -> int:
    """One message per year since 2016, all with one system time (now)."""
    with sessions()() as session:
        now = _now(session)
    years = list(range(FACTORS_BACKFILL_SINCE, now.year + 1))
    for year in years:
        backfill_factors.send(year, now.isoformat(), market)
    return len(years)


def start_taiwan_factor_backfill() -> int:
    """The Taiwan universe's snapshots at every 0050 session and Taipei month end since 2016,
    under the active TW definitions (ADR-040 TW17, TW26)."""
    return start_factor_backfill("TW")


# ---------- paper portfolio (M2.3) ----------


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def snapshot_portfolio(trigger: str) -> None:
    """The paper portfolio now (T = S = now) and its drawdown alert (ADR-031 R4)."""
    with sessions()() as session:
        now = _now(session)
        rules = risk.stored_risk_rules(session)
        if rules is None:
            logger.warning("Risk rules not loaded (make migrate): no portfolio snapshot")
            return
        snapshot = risk.record_portfolio(session, rules, now, now, trigger)
        session.commit()
        logger.info(
            "Paper portfolio at %s (%s): equity %s, drawdown %s%%",
            now,
            trigger,
            snapshot.equity,
            snapshot.drawdown_pct,
        )


def start_portfolio_snapshot(*, manual: bool) -> None:
    snapshot_portfolio.send("manual" if manual else "schedule")


# ---------- real holdings (M3.10) ----------


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def snapshot_holdings(trigger: str) -> None:
    """Steven's recorded holdings now (T = S = now; ADR-041 H2). Nothing when none recorded.
    The log names no position (H12)."""
    with sessions()() as session:
        now = _now(session)
        snapshot = holdings.record_snapshot(session, now, now, trigger)
        session.commit()
        if snapshot is None:
            logger.info("No holdings recorded: no holdings snapshot")
            return
        logger.info(
            "Holdings snapshot at %s (%s): %s positions, valuation %s",
            now,
            trigger,
            snapshot.positions,
            snapshot.valuation_version,
        )


def start_holdings_snapshot(*, manual: bool) -> None:
    snapshot_holdings.send("manual" if manual else "schedule")


# ---------- S3 ETF rotation (M2.4) ----------

ROTATION_BACKFILL_SINCE = date(2017, 1, 1)  # ADR-032: 12-1 momentum needs a year of closes
ROTATION_TIME_LIMIT_MS = 60 * 60 * 1000  # every session since 2017, in order


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def evaluate_rotation(trigger: str) -> None:
    """The rotation now (T = S = now): signals of a new target and its alert (ADR-032)."""
    with sessions()() as session:
        now = _now(session)
        rules = rotation.stored_rotation_rules(session)
        if rules is None:
            logger.warning("Rotation rules not loaded (make migrate): nothing assessed")
            return
        row = rotation.record_rotation(session, rules, now, now, trigger)
        # read before the commit expires the row: a DetachedInstanceError here used to make
        # dramatiq retry, storing a second assessment at a later T (KI-24)
        stored = f"{row.reason}, target {row.target}" if row is not None else "already stored"
        session.commit()
    logger.info("Rotation at %s (%s): %s", now, trigger, stored)


@dramatiq.actor(
    queue_name=EVALUATION_QUEUE, max_retries=1, time_limit=ROTATION_TIME_LIMIT_MS, broker=broker
)
def backfill_rotation(system_time: str) -> None:
    """The rotation at every session close and month end since 2017, in order, as the database
    held it at `system_time` (each compares with the previous point of the run)."""
    held = datetime.fromisoformat(system_time)
    with sessions()() as session:
        rules = rotation.stored_rotation_rules(session)
        if rules is None:
            logger.warning("Rotation rules not loaded (make migrate): nothing assessed")
            return
        points = factors.session_points(session, REGIME_CALENDAR, ROTATION_BACKFILL_SINCE, held)
        stored = rotation.record_points(session, rules, points, held, "backfill")
    logger.info("Rotation backfill: %d points, %d stored", len(points), stored)


def start_rotation_evaluation(*, manual: bool) -> None:
    evaluate_rotation.send("manual" if manual else "schedule")


def start_rotation_backfill() -> int:
    """One message for every session close and month end since 2017 (in order; month ends only
    under rotation rules 0.1.0), with one system time (now)."""
    with sessions()() as session:
        now = _now(session)
        points = factors.session_points(session, REGIME_CALENDAR, ROTATION_BACKFILL_SINCE, now)
    backfill_rotation.send(now.isoformat())
    return len(points)


# ---------- S4 momentum (M3.0) ----------

MOMENTUM_BACKFILL_SINCE = date(2017, 1, 1)  # ADR-033: 12-1 momentum needs a year of closes
MOMENTUM_TIME_LIMIT_MS = 60 * 60 * 1000  # every session since 2017, in order


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def evaluate_momentum(trigger: str) -> None:
    """S4 now (T = S = now) and the signals of a newly set target (ADR-036 D7)."""
    with sessions()() as session:
        now = _now(session)
        rules = backtest.stored_momentum_rules(session)
        if rules is None:
            logger.warning("Momentum rules not loaded (make migrate): nothing assessed")
            return
        row = momentum.record_momentum(session, rules, now, now, trigger)
        stored = f"{row.reason}, target {row.target}" if row is not None else "already stored"
        session.commit()  # after reading the row (KI-24)
    logger.info("S4 momentum at %s (%s): %s", now, trigger, stored)


@dramatiq.actor(
    queue_name=EVALUATION_QUEUE, max_retries=1, time_limit=MOMENTUM_TIME_LIMIT_MS, broker=broker
)
def backfill_momentum(system_time: str) -> None:
    """S4 at every session close and month end since 2017, in order, as the database held it
    at `system_time` (each carries the previous point of the run)."""
    held = datetime.fromisoformat(system_time)
    with sessions()() as session:
        rules = backtest.stored_momentum_rules(session)
        if rules is None:
            logger.warning("Momentum rules not loaded (make migrate): nothing assessed")
            return
        points = factors.session_points(session, REGIME_CALENDAR, MOMENTUM_BACKFILL_SINCE, held)
        stored = momentum.record_points(session, rules, points, held, "backfill")
    logger.info("S4 momentum backfill: %d points, %d stored", len(points), stored)


def start_momentum_evaluation(*, manual: bool) -> None:
    evaluate_momentum.send("manual" if manual else "schedule")


def start_momentum_backfill() -> int:
    """One message for every session close and month end since 2017 (in order), with one
    system time (now)."""
    with sessions()() as session:
        now = _now(session)
        points = factors.session_points(session, REGIME_CALENDAR, MOMENTUM_BACKFILL_SINCE, now)
    backfill_momentum.send(now.isoformat())
    return len(points)


# ---------- Taiwan screens (M3.11) ----------

SCREENS_TIME_LIMIT_MS = 60 * 60 * 1000  # every session since 2024, in batches


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=1, broker=broker)
def evaluate_screens(trigger: str) -> None:
    """The Taiwan screens of the newest stored session (ADR-042 SC11), or a not-judged row for
    a calendar session whose TWSE files have not come."""
    from autotrading.domain.markets import TW
    from autotrading.repositories import screens

    with sessions()() as session:
        now = _now(session)
        rules = screens.stored_screen_rules(session)
        if rules is None:
            logger.warning("Screen rules not loaded (make migrate): nothing judged")
            return
        row = screens.record_live(session, rules, now, trigger, market_calendar(TW.exchange))
        found = f"{row.session} {row.status}" if row is not None else "nothing new"
        session.commit()
    logger.info("Taiwan screens at %s (%s): %s", now, trigger, found)


@dramatiq.actor(
    queue_name=EVALUATION_QUEUE, max_retries=1, time_limit=SCREENS_TIME_LIMIT_MS, broker=broker
)
def backfill_screens(system_time: str, since: str | None = None) -> None:
    """The Taiwan screens at every stored session not judged yet, in order, as the database held
    it at `system_time` (the history check, ADR-042 SC13)."""
    from autotrading.repositories import screens

    held = datetime.fromisoformat(system_time)
    with sessions()() as session:
        rules = screens.stored_screen_rules(session)
        if rules is None:
            logger.warning("Screen rules not loaded (make migrate): nothing judged")
            return
        stored = screens.backfill(
            session, rules, held, since=date.fromisoformat(since) if since else None
        )
    logger.info("Taiwan screens backfill: %d runs stored", stored)


def start_screens_evaluation(*, manual: bool) -> None:
    evaluate_screens.send("manual" if manual else "schedule")


def start_screens_backfill(since: date | None = None) -> None:
    with sessions()() as session:
        now = _now(session)
    backfill_screens.send(now.isoformat(), since.isoformat() if since else None)


# ---------- alert delivery (M3.0b) ----------

DELIVERY_RATE = 1.0  # messages a second to one chat (Telegram allows about one)
DELIVERY_BURST = 3


@dramatiq.actor(queue_name="system", max_retries=0, time_limit=120_000, broker=broker)
def deliver_alerts(trigger: str) -> None:
    """Push the alerts the active delivery rules choose to Steven's Telegram chat (ADR-037).
    Without TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID nothing is sent. A failure is recorded
    and tried again on the next run (no Dramatiq retry)."""
    if not telegram.configured(_settings):
        return
    limiter = TokenBucketLimiter(_redis)
    with sessions()() as session:
        now = _now(session)
        rules = delivery.stored_delivery_rules(session)
        if rules is None:
            logger.warning("Delivery rules not loaded (make migrate): nothing sent")
            return
        chat = telegram.chat_id(_settings)
        with telegram.TelegramClient.from_settings(_settings) as client:
            sent, failed = delivery.deliver(
                session,
                rules,
                lambda text: client.send(chat, text),
                now,
                lambda: limiter.acquire(
                    "telegram", rate=DELIVERY_RATE, burst=DELIVERY_BURST, timeout=60
                ),
            )
    if sent or failed:
        logger.info("Telegram delivery (%s): %d sent, %d failed", trigger, sent, failed)


def start_alert_delivery(*, manual: bool) -> None:
    deliver_alerts.send("manual" if manual else "schedule")


@dramatiq.actor(queue_name="system", max_retries=0, time_limit=300_000, broker=broker)
def deliver_digest(trigger: str) -> None:
    """The week's digest of every rule candidate (ADR-038): checked hourly, sent once on the
    delivery rules' weekday and hour; `manual` sends this week's now if not sent yet."""
    if not telegram.configured(_settings):
        return
    with sessions()() as session:
        now = _now(session)
        rules = delivery.stored_delivery_rules(session)
        if rules is None:
            logger.warning("Delivery rules not loaded (make migrate): no digest")
            return
        chat = telegram.chat_id(_settings)
        with telegram.TelegramClient.from_settings(_settings) as client:
            sent = delivery.deliver_digest(
                session,
                rules,
                lambda text: client.send(chat, text),
                now,
                force=trigger == "manual",
            )
    if sent:
        logger.info("Telegram digest (%s): %d messages sent", trigger, sent)


def start_digest(*, manual: bool) -> None:
    deliver_digest.send("manual" if manual else "schedule")


# ---------- backtests (M2.5) ----------

BACKTEST_TIME_LIMIT_MS = 60 * 60 * 1000  # three strategies since 2016


@dramatiq.actor(
    queue_name=EVALUATION_QUEUE, max_retries=1, time_limit=BACKTEST_TIME_LIMIT_MS, broker=broker
)
def run_backtests(trigger: str) -> None:
    """Every strategy's backtest now (T = S = now). The schedule runs once a month: it skips
    when a run is known in this New York month (ADR-033 B7)."""
    with sessions()() as session:
        now = _now(session)
        rules = backtest.stored_backtest_rules(session)
        if rules is None:
            logger.warning("Backtest rules not loaded (make migrate): nothing run")
            return
        if trigger == "schedule" and backtest.ran_this_month(session, rules, now):
            logger.info("Backtests at %s: already run this month", now)
            return
        stored = backtest.record_all(session, rules, now, now, trigger)  # type: ignore[arg-type]
    logger.info("Backtests at %s (%s): %d runs stored", now, trigger, len(stored))


def start_backtests(*, manual: bool) -> None:
    run_backtests.send("manual" if manual else "schedule")


def start_buyback_backfill() -> int:
    """One message per month end since BACKFILL_SINCE, all with one system time (now)."""
    with sessions()() as session:
        now = _now(session)
    points = month_ends(buyback_states.BACKFILL_SINCE, now)
    for point in points:
        backfill_buyback_states.send(point.isoformat(), now.isoformat())
    return len(points)
