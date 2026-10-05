"""Container healthcheck for background components.

Usage: `python -m autotrading.jobs.healthcheck worker|scheduler`
Exit code 0 when the component's heartbeat is fresh, 1 when stale or Redis is down.
"""

import sys

from autotrading.infra.heartbeat import Component, probe_heartbeat
from autotrading.infra.redis_client import make_redis
from autotrading.settings import get_settings

COMPONENTS: dict[str, Component] = {"worker": "worker", "scheduler": "scheduler", "queue": "queue"}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in COMPONENTS:
        print("usage: python -m autotrading.jobs.healthcheck worker|scheduler", file=sys.stderr)
        return 2
    result = probe_heartbeat(make_redis(get_settings()), COMPONENTS[argv[1]])
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
