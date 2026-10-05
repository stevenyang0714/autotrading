import threading

from autotrading.jobs.broker import WorkerHeartbeat


def test_worker_heartbeat_beats_until_shutdown() -> None:
    beats = threading.Semaphore(0)
    middleware = WorkerHeartbeat(beats.release, interval_seconds=0.01)

    middleware.after_worker_boot(broker=None, worker=None)  # type: ignore[arg-type]
    assert beats.acquire(timeout=2)
    assert beats.acquire(timeout=2)  # keeps beating on its own, independent of the scheduler
    middleware.before_worker_shutdown(broker=None, worker=None)  # type: ignore[arg-type]
    assert middleware._thread is not None and not middleware._thread.is_alive()


def test_worker_heartbeat_survives_a_failing_beat() -> None:
    calls: list[int] = []
    done = threading.Event()

    def flaky() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("redis down")
        done.set()

    middleware = WorkerHeartbeat(flaky, interval_seconds=0.01)
    middleware.after_worker_boot(broker=None, worker=None)  # type: ignore[arg-type]
    assert done.wait(timeout=2)
    middleware.before_worker_shutdown(broker=None, worker=None)  # type: ignore[arg-type]
