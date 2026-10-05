"""Dramatiq wiring for ingestion: the run_ingestion actor and dead-letter recording.

Built by a factory so production binds it to the Redis broker and tests to a StubBroker.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import dramatiq
from dramatiq.broker import Broker, MessageProxy
from dramatiq.middleware import CurrentMessage, Middleware

from autotrading.ingestion.runner import IngestionRunner

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


def declare_ingestion_actor(
    broker: Broker,
    runner: Callable[[], IngestionRunner],
    *,
    max_retries: int,
    min_backoff_ms: int,
    max_backoff_ms: int,
) -> Any:
    """Declare run_ingestion on `broker`. `runner` is called lazily inside the worker."""
    if not any(isinstance(m, CurrentMessage) for m in broker.middleware):
        broker.add_middleware(CurrentMessage())
    broker.add_middleware(DeadLetterRecorder(lambda run_id: runner().record_dead_letter(run_id)))

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
    )
    return decorate(run_ingestion)
