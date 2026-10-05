from fastapi.testclient import TestClient

from autotrading.api.health import overall_status
from autotrading.infra.probes import ProbeResult
from autotrading.main import create_app

OK = ProbeResult("ok", 1.0, None)


class FakeChecker:
    def __init__(
        self,
        core: dict[str, ProbeResult] | None = None,
        background: dict[str, ProbeResult] | None = None,
    ) -> None:
        self._core = core or {"database": OK, "redis": OK, "object_store": OK}
        self._background = background or {"worker": OK, "scheduler": OK}

    def core(self) -> dict[str, ProbeResult]:
        return self._core

    def background(self) -> dict[str, ProbeResult]:
        return self._background


def get_health(checker: FakeChecker) -> tuple[int, dict[str, object]]:
    with TestClient(create_app(health_checker=checker)) as client:
        response = client.get("/health")
    return response.status_code, response.json()


def test_live_does_not_touch_dependencies() -> None:
    down = ProbeResult("down", 1.0, "OperationalError")
    checker = FakeChecker(core={"database": down, "redis": down, "object_store": down})
    with TestClient(create_app(health_checker=checker)) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_all_green() -> None:
    status_code, body = get_health(FakeChecker())
    assert status_code == 200
    assert body["status"] == "ok"
    components = body["components"]
    assert isinstance(components, dict)
    assert set(components) == {"database", "redis", "object_store", "worker", "scheduler"}


def test_core_dependency_down_returns_503() -> None:
    down = ProbeResult("down", 2000.0, "OperationalError")
    status_code, body = get_health(
        FakeChecker(core={"database": down, "redis": OK, "object_store": OK})
    )
    assert status_code == 503
    assert body["status"] == "down"


def test_stale_heartbeat_is_degraded_not_red() -> None:
    stale = ProbeResult("stale", 1.0, "no heartbeat within TTL")
    status_code, body = get_health(FakeChecker(background={"worker": stale, "scheduler": OK}))
    assert status_code == 200
    assert body["status"] == "degraded"


def test_overall_status_precedence() -> None:
    down = ProbeResult("down", 1.0, None)
    stale = ProbeResult("stale", 1.0, None)
    assert overall_status({"db": OK}, {"worker": OK}) == "ok"
    assert overall_status({"db": OK}, {"worker": stale}) == "degraded"
    assert overall_status({"db": down}, {"worker": stale}) == "down"
