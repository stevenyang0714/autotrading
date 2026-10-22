"""Runs ingestion jobs (M0.3).

Per run: idempotency check -> rate-limited fetch -> raw payloads to the object store ->
one database transaction that records the payloads, writes facts and marks the run succeeded.
A failure marks the run failed and re-raises so Dramatiq retries it; after the last retry the
dead-letter middleware calls record_dead_letter. An attempt stopped by Dramatiq's time limit is a
failure too. A worker process killed mid-run writes nothing: the next worker marks such runs
failed (error class Interrupted) before it takes its first message (mark_interrupted).
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.db.models import DeadLetter, IngestionRun, Source
from autotrading.ingestion.errors import sanitize_error
from autotrading.ingestion.job import (
    JOB_REGISTRY,
    RUN_TIME_LIMIT_SECONDS,
    FetchContext,
    IngestionJob,
    JobRegistry,
    StoreContext,
    Window,
    idempotency_key,
)
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore, record_payloads
from autotrading.repositories.audit import set_actor

FINISHED_STATUSES = ("succeeded", "skipped", "dead_lettered")
SUCCEEDED_KEY_INDEX = "uq_ingestion_runs_succeeded_key"
INTERRUPTED = "Interrupted"
INTERRUPTED_MESSAGE = (
    "the worker stopped before this attempt finished; finished_at is the latest it can have ended"
)
STOPPED_MESSAGE = "stopped before the attempt finished (time limit or worker shutdown)"


class IngestionRunner:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        raw_store: RawPayloadStore,
        limiter: TokenBucketLimiter,
        registry: JobRegistry | None = None,
    ) -> None:
        self._sessions = sessions
        self._raw_store = raw_store
        self._limiter = limiter
        self._registry = JOB_REGISTRY if registry is None else registry

    @property
    def sessions(self) -> sessionmaker[Session]:
        return self._sessions

    def create_run(self, job: str, params: dict[str, Any], window: Window | None = None) -> UUID:
        """Record a queued run; the caller then sends its id to the run_ingestion actor."""
        job_class = self._job_class(job)
        window = window or Window()
        with self._sessions() as session:
            run = IngestionRun(
                source_id=job_class.source_id,
                job=job,
                params=params,
                window_start=window.start,
                window_end=window.end,
                idempotency_key=idempotency_key(job_class.source_id, job, params, window),
                status="queued",
            )
            session.add(run)
            session.commit()
            return run.id

    def execute(self, run_id: UUID, *, attempt: int = 1) -> str:
        """Run once; returns the final status. Raises on failure so the broker can retry."""
        with self._sessions() as session:
            run = session.get(IngestionRun, run_id, with_for_update=True)
            if run is None:
                raise LookupError(f"ingestion run {run_id} not found")
            if run.status in FINISHED_STATUSES:
                return run.status
            if self._key_already_succeeded(session, run):
                self._set_status(session, run_id, "skipped")
                session.commit()
                return "skipped"
            source = session.get_one(Source, run.source_id)
            rate, burst = source.rate_limit_per_second, source.rate_limit_burst
            job = self._job_class(run.job)(
                run.params, Window(start=run.window_start, end=run.window_end)
            )
            session.execute(
                update(IngestionRun)
                .where(IngestionRun.id == run_id)
                .values(status="running", attempt=attempt, started_at=func.now(), finished_at=None)
            )
            session.commit()

        source_id = job.source_id
        try:
            fetched = job.fetch(
                FetchContext(
                    run_id=run_id,
                    acquire=lambda: self._limiter.acquire(source_id, rate=rate, burst=burst),
                    sessions=self._sessions,
                )
            )
            stored = [self._raw_store.put(source_id, payload) for payload in fetched]
            with self._sessions() as session:
                set_actor(session, f"ingest:{source_id}")
                record_payloads(session, source_id, run_id, stored)
                result = job.store(StoreContext(session=session, run_id=run_id, payloads=stored))
                session.execute(
                    update(IngestionRun)
                    .where(IngestionRun.id == run_id)
                    .values(
                        status="succeeded",
                        finished_at=func.now(),
                        rows_inserted=result.inserted,
                        rows_unchanged=result.unchanged,
                        rows_conflicted=result.conflicted,
                        notes=list(result.notes),
                        raw_payload_keys=[payload.object_key for payload in stored],
                        error_class=None,
                        error_message=None,
                    )
                )
                session.commit()
        except IntegrityError as exc:
            if SUCCEEDED_KEY_INDEX not in str(exc.orig):
                self._mark_failed(run_id, exc)
                raise
            # Another run with the same key succeeded first; this transaction rolled back.
            with self._sessions() as session:
                self._set_status(session, run_id, "skipped")
                session.commit()
            return "skipped"
        except BaseException as exc:
            # Dramatiq's TimeLimitExceeded derives from BaseException (dramatiq Interrupt): record
            # the attempt before the broker retries or dead-letters it.
            self._mark_failed(run_id, exc)
            raise
        return "succeeded"

    def record_dead_letter(self, run_id: UUID) -> None:
        """Called once the broker has given up on the run's message."""
        with self._sessions() as session:
            set_actor(session, "ingest:dead_letter")
            run = session.get(IngestionRun, run_id, with_for_update=True)
            if run is None or run.status in ("succeeded", "dead_lettered"):
                return
            session.execute(
                insert(DeadLetter)
                .values(
                    ingestion_run_id=run.id,
                    source_id=run.source_id,
                    job=run.job,
                    params=run.params,
                    idempotency_key=run.idempotency_key,
                    attempts=run.attempt,
                    error_class=run.error_class,
                    error_message=run.error_message,
                )
                .on_conflict_do_nothing(index_elements=["ingestion_run_id"])
            )
            self._set_status(session, run_id, "dead_lettered")
            session.commit()

    def mark_interrupted(self) -> list[UUID]:
        """Mark every `running` run failed with error class Interrupted.

        Call only when no attempt can be in progress: at worker start, before the first message
        (compose runs one worker process). A run still `running` then belonged to a worker
        process that was killed mid-run. A retry still queued for it runs it again (`failed` is not
        final). finished_at is the attempt's start plus the time limit, or now if earlier, so an
        old run does not become a source's latest attempt on Data Health.
        """
        limit = timedelta(seconds=RUN_TIME_LIMIT_SECONDS)
        with self._sessions() as session:
            marked = session.scalars(
                update(IngestionRun)
                .where(IngestionRun.status == "running")
                .values(
                    status="failed",
                    finished_at=func.least(func.now(), IngestionRun.started_at + limit),
                    error_class=INTERRUPTED,
                    error_message=INTERRUPTED_MESSAGE,
                )
                .returning(IngestionRun.id)
            ).all()
            session.commit()
        return list(marked)

    def _job_class(self, job: str) -> type[IngestionJob]:
        try:
            return self._registry[job]
        except KeyError:
            raise LookupError(f"unknown ingestion job {job!r}") from None

    @staticmethod
    def _key_already_succeeded(session: Session, run: IngestionRun) -> bool:
        query = select(
            exists().where(
                IngestionRun.idempotency_key == run.idempotency_key,
                IngestionRun.status == "succeeded",
            )
        )
        return bool(session.scalar(query))

    @staticmethod
    def _set_status(session: Session, run_id: UUID, status: str) -> None:
        session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(status=status, finished_at=func.now())
        )

    def _mark_failed(self, run_id: UUID, exc: BaseException) -> None:
        error_class, error_message = sanitize_error(exc)
        if not error_message and not isinstance(exc, Exception):
            error_message = STOPPED_MESSAGE
        with self._sessions() as session:
            session.execute(
                update(IngestionRun)
                .where(IngestionRun.id == run_id)
                .values(
                    status="failed",
                    finished_at=func.now(),
                    error_class=error_class,
                    error_message=error_message,
                )
            )
            session.commit()
