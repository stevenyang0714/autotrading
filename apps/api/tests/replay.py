"""CI only (`make replay-fixtures`): load the recorded SEC, FRED and Alpaca responses into the
stack database through the real ingestion jobs, offline and without credentials, so the e2e
tests see real data. Prices are labelled `fixture`, so the UI shows its DEMO DATA banner
(ADR-006).

    cd apps/api && uv run python -m tests.replay
"""

from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from autotrading.adapters.sec.refresh import universe_predecessors
from autotrading.infra.db import make_engine
from autotrading.infra.object_store import ensure_bucket, make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window
from autotrading.settings import get_settings
from tests import alpaca_replay, fred_replay, sec_replay


def main() -> None:
    settings = get_settings()
    s3 = make_s3_client(settings)
    ensure_bucket(s3, settings.s3_bucket)
    runner = IngestionRunner(
        sessionmaker(make_engine(settings)),
        RawPayloadStore(s3, settings.s3_bucket),
        TokenBucketLimiter(make_redis(settings)),
        alpaca_replay.register_recorded(
            fred_replay.register_recorded(sec_replay.recorded_registry())
        ),
    )
    window = refresh_window(datetime.now(UTC), manual=True)
    sec_runs = sec_replay.replay(
        runner, window, universe_predecessors(settings.resolved_config_dir())
    )
    fred_runs = fred_replay.replay(runner, window)
    alpaca_runs = alpaca_replay.replay(runner, window)
    print(
        f"replayed {len(sec_runs)} SEC, {len(fred_runs)} FRED and {len(alpaca_runs)} Alpaca "
        "runs from recorded fixtures"
    )


if __name__ == "__main__":
    main()
