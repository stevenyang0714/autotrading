import os

import httpx2 as httpx
import pytest

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def api_url() -> str:
    """Fail loudly (never skip) when the stack is down, so a broken stack can't pass CI."""
    try:
        httpx.get(f"{API_URL}/health/live", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.fail(
            f"Local stack is not reachable at {API_URL}. Run `make up` first.", pytrace=False
        )
    return API_URL
