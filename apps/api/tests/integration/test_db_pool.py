"""Request connections ride out a database that is slow to accept connections, while the
health probe keeps its 2 s limit; a page's burst of API calls reuses pooled connections.

Runs against an empty throwaway database; nothing is written.
"""

import contextlib
import socket
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL

from autotrading.infra.db import make_engine, make_probe_engine, probe_database
from autotrading.infra.probes import PROBE_TIMEOUT_SECONDS
from autotrading.settings import Settings

pytestmark = pytest.mark.integration

ACCEPT_DELAY_SECONDS = PROBE_TIMEOUT_SECONDS + 1
# The instrument page's Promise.all (apps/web/src/app/instruments/[ticker]/page.tsx).
INSTRUMENT_PAGE_API_CALLS = 13


class SlowAcceptProxy:
    """Forwards TCP to the database, but every new connection first waits `delay` seconds,
    like a server too busy to accept connections promptly. Established connections are
    not slowed down."""

    def __init__(self, host: str, port: int, delay: float) -> None:
        self._upstream = (host, port)
        self._delay = delay
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self._listener.accept()
            except OSError:
                return  # closed
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket) -> None:
        time.sleep(self._delay)
        try:
            upstream = socket.create_connection(self._upstream)
        except OSError:
            client.close()
            return
        threading.Thread(target=self._pipe, args=(upstream, client), daemon=True).start()
        self._pipe(client, upstream)

    @staticmethod
    def _pipe(source: socket.socket, target: socket.socket) -> None:
        with contextlib.suppress(OSError):
            while data := source.recv(65536):
                target.sendall(data)
        for sock in (source, target):
            sock.close()

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._listener.shutdown(socket.SHUT_RDWR)
        self._listener.close()


def settings_for(url: URL) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, database_url=SecretStr(url.render_as_string(hide_password=False))
    )


@pytest.fixture(scope="module")
def database(database_factory: Callable[[], URL]) -> URL:
    return database_factory()


@pytest.fixture
def slow_database(database: URL) -> Iterator[URL]:
    host, port = database.host or "localhost", database.port or 5432
    proxy = SlowAcceptProxy(host, port, ACCEPT_DELAY_SECONDS)
    yield database.set(host="127.0.0.1", port=proxy.port)
    proxy.close()


def test_a_request_waits_for_a_slow_database_instead_of_failing(slow_database: URL) -> None:
    engine = make_engine(settings_for(slow_database))
    try:
        started = time.monotonic()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
        assert time.monotonic() - started >= ACCEPT_DELAY_SECONDS
    finally:
        engine.dispose()


def test_the_health_probe_reports_a_slow_database_within_its_timeout(slow_database: URL) -> None:
    engine = make_probe_engine(settings_for(slow_database))
    try:
        result = probe_database(engine)
    finally:
        engine.dispose()
    assert result.status == "down"
    assert result.detail == "OperationalError"
    assert result.latency_ms < ACCEPT_DELAY_SECONDS * 1000


def page_burst(engine: Engine) -> set[int]:
    """Hold one connection per instrument-page API call at the same time; return the
    server process IDs behind them."""
    barrier = threading.Barrier(INSTRUMENT_PAGE_API_CALLS)

    def call(_: int) -> int:
        with engine.connect() as conn:
            pid: int = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            barrier.wait(timeout=30)
        return pid

    with ThreadPoolExecutor(INSTRUMENT_PAGE_API_CALLS) as pool:
        return set(pool.map(call, range(INSTRUMENT_PAGE_API_CALLS)))


def test_the_next_page_load_reuses_the_pooled_connections(database: URL) -> None:
    engine = make_engine(settings_for(database))
    try:
        first = page_burst(engine)
        second = page_burst(engine)
    finally:
        engine.dispose()
    assert len(first) == INSTRUMENT_PAGE_API_CALLS
    assert second == first  # no new connection was opened for the second page
