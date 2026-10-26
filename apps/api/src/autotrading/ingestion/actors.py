"""Dramatiq wiring for ingestion: the run_ingestion actor, dead-letter recording and marking
runs a killed worker left `running`.

Built by a factory so production binds it to the Redis broker and tests to a StubBroker.
"""

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import dramatiq
from dramatiq.broker import Broker, MessageProxy
from dramatiq.middleware import CurrentMessage, Middleware
from dramatiq.worker import Worker

from autotrading.ingestion.job import RUN_TIME_LIMIT_SECONDS
from autotrading.ingestion.runner import IngestionRunner

logger = logging.getLogger(__name__)

INGESTION_ACTOR = "run_ingestion"
INGESTION_QUEUE = "ingestion"


class DeadLetterRecorder(Middleware):
    """After the Retries middleware gives up, the worker nacks the message to the broker's
    dead-letter queue; this records it in the database so the API and UI can show it."""

    def __init__(self, record: Callable[[UUID], None]) -> None:
        self._record = record

    def after_nack(self, broker: Broker, message: MessageProxy) -> None:
        if message.actor_name == INGESTION_ACTOR:
            self._record(UUID(message.args[0]))


class InterruptedRunRecorder(Middleware):
    """When a worker starts, before its consumers take a message, runs still `running` were left
    by a worker process that was killed mid-run (container recreated, Docker restarted): they
    are marked failed with error class Interrupted. A failure here never stops the worker."""

    def __init__(self, mark: Callable[[], list[UUID]]) -> None:
        self._mark = mark

    def before_worker_boot(self, broker: Broker, worker: Worker) -> None:
        try:
            marked = self._mark()
        except Exception as exc:  # database not reachable: the next worker start tries again
            logger.warning("could not mark interrupted ingestion runs: %s", type(exc).__name__)
            return
        if marked:
            logger.warning(
                "marked %d interrupted ingestion run(s) failed: %s",
                len(marked),
                ", ".join(str(run_id) for run_id in marked),
            )


def declare_ingestion_actor(
    broker: Broker,
    runner: Callable[[], IngestionRunner],
    *,
    max_retries: int,
    min_backoff_ms: int,
    max_backoff_ms: int,
    time_limit_ms: int = RUN_TIME_LIMIT_SECONDS * 1000,
) -> Any:
    """Declare run_ingestion on `broker`. `runner` is called lazily inside the worker."""
    if not any(isinstance(m, CurrentMessage) for m in broker.middleware):
        broker.add_middleware(CurrentMessage())
    broker.add_middleware(DeadLetterRecorder(lambda run_id: runner().record_dead_letter(run_id)))
    broker.add_middleware(InterruptedRunRecorder(lambda: runner().mark_interrupted()))

    def run_ingestion(run_id: str) -> str:
        message = CurrentMessage.get_current_message()
        retries = int(message.options.get("retries", 0)) if message is not None else 0
        return runner().execute(UUID(run_id), attempt=retries + 1)

    decorate = dramatiq.actor(
        actor_name=INGESTION_ACTOR,
        queue_name=INGESTION_QUEUE,
        broker=broker,
        max_retries=max_retries,
        min_backoff=min_backoff_ms,
        max_backoff=max_backoff_ms,
        time_limit=time_limit_ms,
    )
    return decorate(run_ingestion)
