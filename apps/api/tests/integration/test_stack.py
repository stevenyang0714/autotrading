import time
from typing import Any

import httpx2 as httpx
import pytest

from autotrading.infra.object_store import make_s3_client
from autotrading.settings import get_settings

pytestmark = pytest.mark.integration

# The first queue heartbeat needs the scheduler -> queue -> worker round trip.
HEALTH_WAIT_SECONDS = 60


def wait_for_green(api_url: str) -> httpx.Response:
    deadline = time.monotonic() + HEALTH_WAIT_SECONDS
    while True:
        response = httpx.get(f"{api_url}/health", timeout=10)
        if response.json().get("status") == "ok" or time.monotonic() > deadline:
            return response
        time.sleep(2)


def test_health_all_green(api_url: str) -> None:
    response = wait_for_green(api_url)
    body: dict[str, Any] = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "ok", body
    for name in ("database", "redis", "object_store", "worker", "scheduler", "queue"):
        assert body["components"][name]["status"] == "ok", (name, body)


def test_timescaledb_extension_available(api_url: str) -> None:
    body = httpx.get(f"{api_url}/health", timeout=10).json()
    assert "timescaledb" in (body["components"]["database"]["detail"] or "")


def test_raw_payload_bucket_exists(api_url: str) -> None:
    settings = get_settings()
    client = make_s3_client(settings)
    client.head_bucket(Bucket=settings.s3_bucket)
