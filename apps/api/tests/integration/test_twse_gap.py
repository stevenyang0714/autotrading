"""M3.7 (ADR-039 TW6, TW9): a Taiwan session no run caught. Synthetic input, built in memory
from the recorded files and labelled here: the 2026-10-22 files re-dated to 2026-10-23, and
their previous margin balances moved by one lot, as a 2026-10-23 file is after a lost
2026-10-22. The margin file must be accepted unverified (not rejected as not yet updated), and
no reference price gap may be claimed across the lost session. Uses its own migrated database.
"""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx2 as httpx
import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.twse.client import TwseClient
from autotrading.config_sync import load_sources, sync_sources
from autotrading.db.models import ExchangeMeasure, IngestionRun, Source
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import JobRegistry, Window, register_job
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.settings import get_settings
from tests.integration.conftest import alembic_config
from tests.twse_replay import DAYS, FIXTURES, RecordedTwseDaily

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 26, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC))
LOST, AFTER = date(2026, 10, 22), date(2026, 10, 23)


def _gap_day() -> dict[str, bytes]:
    """URL -> bytes of the synthetic 2026-10-23 files."""
    out: dict[str, bytes] = {}
    for url, name in DAYS["d2"]["files"].items():
        rows: list[dict[str, Any]] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        if name.endswith("STOCK_DAY_ALL.json"):
            rows = [{**r, "Date": "1151023"} for r in rows]
        elif name.endswith("BWIBBU_d.json"):
            rows = [{**r, "Date": "20261023"} for r in rows]
        elif name.endswith("MI_MARGN.json"):
            rows = [{**r, "融資前日餘額": str(int(r["融資前日餘額"] or 0) + 1)} for r in rows]
        out[url] = json.dumps(rows, ensure_ascii=False).encode()
    return out


class GapTwseDaily(RecordedTwseDaily):
    def client(self) -> TwseClient:
        if self.params["fixture_day"] != "gap":
            return super().client()
        files = _gap_day()

        def serve(request: httpx.Request) -> httpx.Response:
            body = files.get(str(request.url))
            return httpx.Response(200, content=body) if body else httpx.Response(404)

        return TwseClient(transport=httpx.MockTransport(serve), sleep=lambda _: None)


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    with Session(engine) as session:
        sync_sources(session, load_sources(get_settings().resolved_config_dir() / "sources.yaml"))
        source = session.get_one(Source, "twse_openapi")
        source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def runner(engine: Engine) -> Iterator[IngestionRunner]:
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    registry: JobRegistry = {}
    register_job(GapTwseDaily, registry)
    yield IngestionRunner(
        sessionmaker(engine),
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        registry,
    )
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


def _run(runner: IngestionRunner, day: str) -> IngestionRun:
    run_id = runner.create_run("twse.daily", {"slot": "test", "fixture_day": day}, WINDOW)
    runner.execute(run_id)
    with runner.sessions() as session:
        return session.get_one(IngestionRun, run_id)


def test_after_a_lost_session_the_margin_file_is_kept_unverified(
    engine: Engine, runner: IngestionRunner
) -> None:
    assert _run(runner, "d1").status == "succeeded"
    after = _run(runner, "gap")
    assert after.status == "succeeded", after.error_message
    assert any(f"sessions lost: {LOST}" in n for n in after.notes)
    assert any(f"MI_MARGN dated {AFTER}" in n for n in after.notes)
    assert not any("still shows an earlier session" in n for n in after.notes)
    # TWSE's reference is the lost session's close: no gap is claimed against 2026-10-21's
    assert not any("reference price" in n for n in after.notes)
    with Session(engine) as session:
        stored = session.scalars(
            select(ExchangeMeasure).where(
                ExchangeMeasure.symbol == "2330",
                ExchangeMeasure.measure_id == "margin_balance",
                ExchangeMeasure.session_date == AFTER,
            )
        ).one()
        assert stored.confidence == Decimal("0.900")
