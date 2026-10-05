"""Dramatiq broker configuration (Redis broker, ADR-002)."""

import logging
import threading
from collections.abc import Callable

import dramatiq
from dramatiq.broker import Broker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
from dramatiq.worker import Worker

from autotrading.infra.heartbeat import HEARTBEAT_INTERVAL_SECONDS
from autotrading.settings import Settings


def configure_broker(settings: Settings) -> RedisBroker:
    """Create the Redis broker and install it as Dramatiq's global broker.

    Must run before any actor is declared: actors bind to the broker at decoration time.
    """
    broker = RedisBroker(url=settings.redis_url)
    dramatiq.set_broker(broker)
    return broker


logger = logging.getLogger(__name__)


class WorkerHeartbeat(Middleware):
    """Writes the worker's own heartbeat from a background thread while the worker runs."""

    def __init__(
        self, beat: Callable[[], None], interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS
    ) -> None:
        self._beat = beat
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def after_worker_boot(self, broker: Broker, worker: Worker) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="worker-heartbeat", daemon=True)
        self._thread.start()

    def before_worker_shutdown(self, broker: Broker, worker: Worker) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._beat()
            except Exception as exc:  # Redis briefly down: report on the next beat
                logger.warning("worker heartbeat failed: %s", type(exc).__name__)
            self._stop.wait(self._interval)
