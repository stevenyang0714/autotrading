"""CI only (`make replay-fixtures`): load the recorded SEC, FRED, Alpaca and news responses
into the stack database through the real ingestion jobs, offline and without credentials, so
the e2e tests see real data. Prices and news are labelled `fixture`, so the UI shows its
DEMO DATA banner (ADR-006).

    cd apps/api && uv run python -m tests.replay
"""

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from autotrading.adapters.sec.refresh import universe_predecessors
from autotrading.api.buyback_states import evaluate_universe
from autotrading.domain.fair_value import month_ends
from autotrading.infra.db import make_engine
from autotrading.infra.object_store import ensure_bucket, make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window
from autotrading.repositories.factors import record_universe, stored_definitions
from autotrading.repositories.regime import record_regime, stored_regime_rules
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay, news_replay, sec_replay

REPLAY_BACKFILL_SINCE = date(2025, 1, 1)  # enough history for the pages, short for CI


def main() -> None:
    settings = get_settings()
    s3 = make_s3_client(settings)
    ensure_bucket(s3, settings.s3_bucket)
    runner = IngestionRunner(
        sessionmaker(make_engine(settings)),
        RawPayloadStore(s3, settings.s3_bucket),
        TokenBucketLimiter(make_redis(settings)),
        news_replay.register_recorded(
            alpaca_replay.register_recorded(
                fred_replay.register_recorded(sec_replay.recorded_registry())
            )
        ),
    )
    window = refresh_window(datetime.now(UTC), manual=True)
    sec_runs = sec_replay.replay(
        runner,
        window,
        universe_predecessors(settings.resolved_config_dir()),
        before_instances=lambda: alpaca_replay.replay_splits(runner, window),
    )
    fred_runs = fred_replay.replay(runner, window)
    alpaca_runs = alpaca_replay.replay(runner, window)
    news_runs = news_replay.replay(runner, window)
    print(
        f"replayed {len(sec_runs)} SEC, {len(fred_runs)} FRED, {len(alpaca_runs)} Alpaca and "
        f"{len(news_runs)} news runs from recorded fixtures"
    )
    # Buyback states (M1.4b) now and at the month ends since REPLAY_BACKFILL_SINCE, as the
    # daily job and `make buyback-backfill` store them, so the pages have states and history.
    with sessionmaker(make_engine(settings))() as session:
        now = session.execute(select(func.now())).scalar_one()
        points = [*month_ends(REPLAY_BACKFILL_SINCE, now), now]
        stored = sum(evaluate_universe(session, at, now, "replay") for at in points)
        # The macro regime (M2.1) at the same points, so the Market Regime page has history.
        rules = stored_regime_rules(session)
        assert rules is not None, "regime rules not loaded: run `make migrate` first"
        regimes = sum(record_regime(session, rules, at, now, "replay") is not None for at in points)
        session.commit()
        # Factor snapshots (M2.2) of every instrument at the same points, all measures.
        definitions = stored_definitions(session)
        assert definitions is not None, "factor definitions not loaded: run `make migrate` first"
        snapshots = record_universe(
            session, definitions, [(at, "all") for at in points], now, "replay"
        )
    print(
        f"stored {stored} buyback state assignments, {regimes} regime assessments and "
        f"{snapshots} factor snapshots"
    )


if __name__ == "__main__":
    main()
