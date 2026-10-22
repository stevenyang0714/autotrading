"""M0.3 acceptance: idempotent runs, dead letters after retries, rate limiting, source config
sync and the Data Health API. Uses the throwaway test database, a throwaway bucket and
namespaced Redis keys; the development data is never touched."""

import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from dramatiq import Worker
from dramatiq.brokers.stub import StubBroker
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.config_sync import SYNC_ACTOR, load_sources, sync_sources
from autotrading.db.models import (
    AuditLog,
    DeadLetter,
    FinancialFact,
    IngestionRun,
    RawPayload,
    Source,
)
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.probes import ProbeResult
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.actors import declare_ingestion_actor
from autotrading.ingestion.job import (
    RUN_TIME_LIMIT_SECONDS,
    FetchContext,
    FetchedPayload,
    IngestionJob,
    JobRegistry,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import INTERRUPTED, STOPPED_MESSAGE, IngestionRunner
from autotrading.main import create_app
from autotrading.repositories.facts import FactConflictError, FinancialFactRepository
from autotrading.settings import Settings, get_settings
from tests.factories import TEST_SOURCE_ID, financial_fact

pytestmark = pytest.mark.integration

PUBLISHED = datetime(2025, 2, 1, 21, 5, tzinfo=UTC)


class FakeFilingJob(IngestionJob):
    """Fetches one JSON document and stores one fact from it."""

    source_id: ClassVar[str] = TEST_SOURCE_ID
    name: ClassVar[str] = "test.fake_filing"

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        ctx.acquire()
        return [
            FetchedPayload(
                content=json.dumps(self.params, sort_keys=True).encode(),
                content_type="application/json",
                source_url="https://example.com/filings/fake.json",
                fetched_at=datetime.now(UTC),
            )
        ]

    def store(self, ctx: StoreContext) -> StoreResult:
        repo = FinancialFactRepository(ctx.session)
        inserted = unchanged = 0
        for payload in ctx.payloads:
            data = json.loads(payload.content)
            fact = financial_fact(
                entity_id=UUID(data["entity_id"]),
                value=data["value"],
                provenance_overrides={
                    "published_at": PUBLISHED,
                    "ingestion_run_id": ctx.run_id,
                    "raw_payload_sha256": payload.sha256,
                },
            )
            created = repo.insert(fact, actor="test:ingest").created
            inserted += created
            unchanged += not created
        return StoreResult(inserted=inserted, unchanged=unchanged)


class AlwaysFailingJob(IngestionJob):
    source_id: ClassVar[str] = TEST_SOURCE_ID
    name: ClassVar[str] = "test.always_fails"

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        raise RuntimeError("provider returned 500 for https://example.com/x?api_key=SECRET123")

    def store(self, ctx: StoreContext) -> StoreResult:  # pragma: no cover - never reached
        raise AssertionError


class SlowJob(IngestionJob):
    """Keeps running Python code until Dramatiq's time limit stops the attempt."""

    source_id: ClassVar[str] = TEST_SOURCE_ID
    name: ClassVar[str] = "test.slow"

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(0.05)
        raise AssertionError("the time limit should have stopped this attempt")

    def store(self, ctx: StoreContext) -> StoreResult:  # pragma: no cover - never reached
        raise AssertionError


class OkChecker:
    def core(self) -> dict[str, ProbeResult]:
        return {}

    def background(self) -> dict[str, ProbeResult]:
        return {}


@pytest.fixture(scope="module")
def registry() -> JobRegistry:
    jobs: JobRegistry = {}
    register_job(FakeFilingJob, jobs)
    register_job(AlwaysFailingJob, jobs)
    register_job(SlowJob, jobs)
    return jobs


@pytest.fixture(scope="module")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="module")
def raw_store(settings: Settings) -> Iterator[tuple[RawPayloadStore, str]]:
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    yield RawPayloadStore(s3, bucket), bucket
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.fixture(scope="module")
def limiter(settings: Settings) -> TokenBucketLimiter:
    return TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}")


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    with Session(engine) as session:  # generous limits so tests are not throttled
        source = session.get_one(Source, TEST_SOURCE_ID)
        source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    return sessionmaker(engine)


@pytest.fixture(scope="module")
def runner(
    sessions: sessionmaker[Session],
    raw_store: tuple[RawPayloadStore, str],
    limiter: TokenBucketLimiter,
    registry: JobRegistry,
) -> IngestionRunner:
    return IngestionRunner(sessions, raw_store[0], limiter, registry)


# ---------- idempotency ----------


def test_same_job_twice_inserts_no_duplicates(
    runner: IngestionRunner,
    sessions: sessionmaker[Session],
    raw_store: tuple[RawPayloadStore, str],
    entity_id: UUID,
    settings: Settings,
) -> None:
    params = {"entity_id": str(entity_id), "value": "100"}
    first = runner.create_run(FakeFilingJob.name, params)
    assert runner.execute(first) == "succeeded"
    second = runner.create_run(FakeFilingJob.name, params)
    assert runner.execute(second) == "skipped"
    assert runner.execute(first) == "succeeded"  # re-delivering a finished message is a no-op

    with sessions() as session:
        run = session.get_one(IngestionRun, first)
        facts = session.scalars(
            select(FinancialFact).where(FinancialFact.entity_id == entity_id)
        ).all()
        payloads = session.scalar(
            select(func.count())
            .select_from(RawPayload)
            .where(RawPayload.object_key.in_(run.raw_payload_keys))
        )
        skipped = session.get_one(IngestionRun, second)
    assert (run.rows_inserted, run.rows_unchanged, len(run.raw_payload_keys)) == (1, 0, 1)
    assert skipped.status == "skipped"
    assert len(facts) == 1 and payloads == 1
    assert facts[0].ingestion_run_id == first
    assert facts[0].raw_payload_sha256 == run.raw_payload_keys[0].rsplit("/", 1)[1]
    _, bucket = raw_store
    s3 = make_s3_client(settings)
    s3.head_object(Bucket=bucket, Key=run.raw_payload_keys[0])  # stored once, content-addressed


def test_new_params_are_a_new_run_and_unchanged_values_are_counted(
    runner: IngestionRunner, sessions: sessionmaker[Session], entity_id: UUID
) -> None:
    first = runner.create_run(FakeFilingJob.name, {"entity_id": str(entity_id), "value": "1"})
    refetch = runner.create_run(
        FakeFilingJob.name, {"entity_id": str(entity_id), "value": "1", "note": "refetch"}
    )
    assert runner.execute(first) == "succeeded"
    assert runner.execute(refetch) == "succeeded"  # different params, different key
    with sessions() as session:
        run = session.get_one(IngestionRun, refetch)
    assert (run.rows_inserted, run.rows_unchanged) == (0, 1)


def test_store_failure_marks_the_run_failed(
    runner: IngestionRunner, sessions: sessionmaker[Session], entity_id: UUID
) -> None:
    ok = runner.create_run(FakeFilingJob.name, {"entity_id": str(entity_id), "value": "1"})
    assert runner.execute(ok) == "succeeded"
    # Same fact key and publication time with another value is a data conflict.
    conflicting = runner.create_run(FakeFilingJob.name, {"entity_id": str(entity_id), "value": "2"})
    with pytest.raises(FactConflictError):
        runner.execute(conflicting)
    with sessions() as session:
        run = session.get_one(IngestionRun, conflicting)
        facts = session.scalar(
            select(func.count())
            .select_from(FinancialFact)
            .where(FinancialFact.entity_id == entity_id)
        )
    assert (run.status, run.error_class) == ("failed", "FactConflictError")
    assert facts == 1  # the failed run's transaction left nothing behind


# ---------- dead letters ----------


def wait_for_status(
    sessions: sessionmaker[Session], run_id: UUID, wanted: str, timeout: float = 20
) -> str:
    """Poll the run until it reaches `wanted` or the timeout passes; the last status seen."""
    deadline = time.monotonic() + timeout
    while True:
        with sessions() as session:
            status = session.get_one(IngestionRun, run_id).status
        if status == wanted or time.monotonic() > deadline:
            return status
        time.sleep(0.1)


def test_failing_job_lands_in_dead_letter_and_api(
    runner: IngestionRunner, sessions: sessionmaker[Session]
) -> None:
    broker = StubBroker()
    broker.emit_after("process_boot")
    actor = declare_ingestion_actor(
        broker, lambda: runner, max_retries=2, min_backoff_ms=1, max_backoff_ms=10
    )
    run_id = runner.create_run(AlwaysFailingJob.name, {"attempt": uuid4().hex})
    actor.send(str(run_id))

    worker = Worker(broker, worker_timeout=50)
    worker.start()
    try:
        status = wait_for_status(sessions, run_id, "dead_lettered")
    finally:
        worker.stop()
    assert status == "dead_lettered"

    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        letters = client.get("/dead-letters").json()
        runs = client.get("/ingestion-runs", params={"status": "dead_lettered"}).json()
    letter = next(item for item in letters if item["ingestion_run_id"] == str(run_id))
    assert letter["attempts"] == 3  # first try + 2 retries
    assert letter["error_class"] == "RuntimeError"
    assert "SECRET123" not in letter["error_message"]
    assert str(run_id) in {run["id"] for run in runs}


# ---------- interrupted attempts ----------


def test_an_attempt_stopped_by_the_time_limit_is_recorded(
    runner: IngestionRunner, sessions: sessionmaker[Session]
) -> None:
    """Dramatiq's TimeLimitExceeded is a BaseException: each stopped attempt is recorded, and
    the dead letter carries its error, not an older one."""
    broker = StubBroker()
    broker.emit_after("process_boot")  # starts the TimeLimit middleware's timer thread
    actor = declare_ingestion_actor(
        broker,
        lambda: runner,
        max_retries=1,
        min_backoff_ms=1,
        max_backoff_ms=10,
        time_limit_ms=300,
    )
    run_id = runner.create_run(SlowJob.name, {"attempt": uuid4().hex})
    actor.send(str(run_id))

    worker = Worker(broker, worker_timeout=50)
    worker.start()
    try:
        status = wait_for_status(sessions, run_id, "dead_lettered", timeout=30)
    finally:
        worker.stop()
    assert status == "dead_lettered"
    with sessions() as session:
        run = session.get_one(IngestionRun, run_id)
        letter = session.scalars(
            select(DeadLetter).where(DeadLetter.ingestion_run_id == run_id)
        ).one()
    assert (run.attempt, run.error_class, run.error_message) == (
        2,
        "TimeLimitExceeded",
        STOPPED_MESSAGE,
    )
    assert (letter.attempts, letter.error_class) == (2, "TimeLimitExceeded")


def set_running(sessions: sessionmaker[Session], run_id: UUID, started_ago: timedelta) -> None:
    """Leave the run as a worker process killed mid-attempt does."""
    with sessions() as session:
        session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(status="running", started_at=func.now() - started_ago, finished_at=None)
        )
        session.commit()


def test_mark_interrupted_fails_only_running_runs(
    runner: IngestionRunner, sessions: sessionmaker[Session]
) -> None:
    old, recent, queued, done = (
        runner.create_run(FakeFilingJob.name, {"interrupted": name})
        for name in ("old", "recent", "queued", "done")
    )
    set_running(sessions, old, timedelta(days=12))
    set_running(sessions, recent, timedelta(minutes=2))
    with sessions() as session:
        session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == done)
            .values(status="succeeded", finished_at=func.now())
        )
        session.commit()

    marked = set(runner.mark_interrupted())

    assert {old, recent} <= marked
    assert not {queued, done} & marked
    limit = timedelta(seconds=RUN_TIME_LIMIT_SECONDS)
    with sessions() as session:
        now = session.execute(select(func.now())).scalar_one()
        runs = {run_id: session.get_one(IngestionRun, run_id) for run_id in (old, recent)}
        others = [session.get_one(IngestionRun, run_id).status for run_id in (queued, done)]
    times = {}
    for run_id, run in runs.items():
        assert (run.status, run.error_class) == ("failed", INTERRUPTED)
        assert run.started_at is not None and run.finished_at is not None
        times[run_id] = (run.started_at, run.finished_at)
    # An old run ends at most a time limit after it started, so it is not a source's latest.
    assert times[old][1] == times[old][0] + limit
    assert times[recent][1] <= now
    assert times[recent][1] < times[recent][0] + limit
    assert others == ["queued", "succeeded"]
    assert not {old, recent} & set(runner.mark_interrupted())  # marked once, not again


def test_a_new_worker_marks_runs_a_killed_worker_left_running(
    runner: IngestionRunner, sessions: sessionmaker[Session], entity_id: UUID
) -> None:
    run_id = runner.create_run(FakeFilingJob.name, {"entity_id": str(entity_id), "value": "3"})
    set_running(sessions, run_id, timedelta(minutes=1))
    broker = StubBroker()
    broker.emit_after("process_boot")
    actor = declare_ingestion_actor(
        broker, lambda: runner, max_retries=0, min_backoff_ms=1, max_backoff_ms=10
    )

    worker = Worker(broker, worker_timeout=50)
    worker.start()  # marks before its consumers take a message
    try:
        with sessions() as session:
            run = session.get_one(IngestionRun, run_id)
            assert (run.status, run.error_class) == ("failed", INTERRUPTED)
        actor.send(str(run_id))  # the killed worker's message, requeued by the broker
        status = wait_for_status(sessions, run_id, "succeeded")
    finally:
        worker.stop()
    assert status == "succeeded"  # failed is not final: the retry runs it again
    with sessions() as session:
        run = session.get_one(IngestionRun, run_id)
    assert (run.error_class, run.error_message, run.rows_inserted) == (None, None, 1)


# ---------- rate limiter ----------


def test_rate_limiter_delays_bursts_per_source(limiter: TokenBucketLimiter) -> None:
    source = f"src_{uuid4().hex[:6]}"
    started = time.monotonic()
    for _ in range(3):  # burst 2, then wait ~1 s for the third token
        limiter.acquire(source, rate=1, burst=2, timeout=5)
    assert time.monotonic() - started >= 0.8

    other = time.monotonic()
    limiter.acquire(f"other_{uuid4().hex[:6]}", rate=1, burst=1, timeout=5)
    assert time.monotonic() - other < 0.5  # another source is not affected


# ---------- source registry config ----------


def test_config_sync_is_idempotent_and_audited(engine: Engine) -> None:
    config = load_sources(get_settings().resolved_config_dir() / "sources.yaml")
    with Session(engine) as session:
        first = sync_sources(session, config)
        session.commit()
    with Session(engine) as session:
        again = sync_sources(session, config)
        session.commit()
    assert {"sec_edgar", "fred", "alpaca_iex", "massive", "gdelt"} <= set(first.created)
    assert again.created == [] and again.updated == []

    changed = config.model_copy(
        update={
            "sources": [
                s.model_copy(update={"priority": 99}) if s.id == "gdelt" else s
                for s in config.sources
            ]
        }
    )
    with Session(engine) as session:
        result = sync_sources(session, changed)
        session.commit()
        entries = session.scalars(
            select(AuditLog).where(AuditLog.object_id == "gdelt").order_by(AuditLog.id)
        ).all()
    assert result.updated == ["gdelt"]
    assert [(e.action, e.actor) for e in entries] == [
        ("insert", SYNC_ACTOR),
        ("update", SYNC_ACTOR),
    ]
    assert (entries[1].details or {})["priority"] == {"old": 40, "new": 99}


def test_source_license_uses_glossary_values(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            Source(
                id=f"lic_{uuid4().hex[:6]}",
                name="Old value",
                url="https://example.com",
                tier=2,
                license_status="terms_of_use",
                update_cadence="daily",
                freshness_sla_seconds=60,
            )
        )
        with pytest.raises(IntegrityError, match="license_status"):
            session.commit()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE raw_payloads SET content_type = 'x' WHERE id = :id",
        "DELETE FROM raw_payloads WHERE id = :id",
    ],
)
def test_raw_payloads_are_append_only(
    runner: IngestionRunner,
    sessions: sessionmaker[Session],
    engine: Engine,
    entity_id: UUID,
    statement: str,
) -> None:
    run_id = runner.create_run(FakeFilingJob.name, {"entity_id": str(entity_id), "value": "7"})
    assert runner.execute(run_id) == "succeeded"
    with sessions() as session:
        payload_id = session.scalars(
            select(RawPayload.id).where(RawPayload.ingestion_run_id == run_id)
        ).one()
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text(statement), {"id": payload_id})


# ---------- data health API ----------


def add_source(session: Session, source_id: str, *, enabled: bool) -> None:
    session.add(
        Source(
            id=source_id,
            name=source_id,
            url="https://example.com",
            tier=1,
            license_status="public",
            update_cadence="daily",
            freshness_sla_seconds=3600,
            enabled=enabled,
        )
    )


def add_run(session: Session, source_id: str, status: str, finished_offset: str) -> None:
    session.add(
        IngestionRun(
            source_id=source_id,
            job="test.fake_filing",
            idempotency_key=uuid4().hex + uuid4().hex,
            status=status,
            finished_at=session.execute(
                text(f"SELECT now() - interval '{finished_offset}'")
            ).scalar_one(),
        )
    )


def test_data_health_reports_freshness(engine: Engine, sessions: sessionmaker[Session]) -> None:
    tag = uuid4().hex[:6]
    fresh, stale, failing, off = (f"{k}_{tag}" for k in ("fresh", "stale", "failing", "off"))
    with Session(engine) as session:
        for source_id in (fresh, stale, failing):
            add_source(session, source_id, enabled=True)
        add_source(session, off, enabled=False)
        session.flush()
        add_run(session, fresh, "succeeded", "10 minutes")
        add_run(session, stale, "succeeded", "2 hours")
        add_run(session, failing, "succeeded", "20 minutes")
        add_run(session, failing, "failed", "5 minutes")
        session.commit()

    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        response = client.get("/data-health")
    assert response.status_code == 200
    by_id: dict[str, Any] = {s["id"]: s for s in response.json()["sources"]}
    assert by_id[fresh]["freshness"] == "fresh"
    assert by_id[stale]["freshness"] == "stale"
    assert by_id[failing]["freshness"] == "failing"
    assert by_id[off]["freshness"] is None
    assert by_id[fresh]["last_run"]["status"] == "succeeded"


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(sessions: sessionmaker[Session]) -> None:
    """Records real API responses (this module's test data) for the web unit tests.

    Runs last in the module, after the runs, dead letters and freshness cases above exist.
    """
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    target.mkdir(parents=True, exist_ok=True)
    with TestClient(create_app(health_checker=OkChecker(), sessions=sessions)) as client:
        for name, path, params in (
            ("data-health", "/data-health", {}),
            ("ingestion-runs", "/ingestion-runs", {"limit": 20}),
            ("dead-letters", "/dead-letters", {}),
        ):
            response = client.get(path, params=params)
            assert response.status_code == 200
            record = {
                "recorded_at": datetime.now(UTC).isoformat(),
                "recorded_from": "integration test database via FastAPI TestClient "
                "(tests/integration/test_ingestion.py)",
                "endpoint": path,
                "response": response.json(),
            }
            (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
