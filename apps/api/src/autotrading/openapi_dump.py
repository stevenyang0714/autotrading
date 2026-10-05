"""Write the API's OpenAPI schema without starting a server.

Usage: `python -m autotrading.openapi_dump <path>` (run by `make gen`). The web app generates
its TypeScript API types from this file (ADR-002).
"""

import json
import sys
from pathlib import Path

from autotrading.main import create_app


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m autotrading.openapi_dump <path>", file=sys.stderr)
        return 2
    Path(argv[1]).write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
