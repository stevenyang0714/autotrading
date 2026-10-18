"""The raw-payload object store for `make db-backup` (OD-8, ADR-034): inside the api container.

    python -m autotrading.jobs.backup_objects --archive > objects.tar.gz
    python -m autotrading.jobs.backup_objects --count

--archive streams every object of the raw-payload bucket as a gzipped tar on standard output
(keys as paths); --count prints the number of objects and their total bytes as JSON, for the
backup manifest. Read-only: nothing in the store is changed. No credential is written anywhere.
"""

import argparse
import io
import json
import sys
import tarfile
from collections.abc import Iterator

from autotrading.infra.object_store import make_s3_client
from autotrading.settings import get_settings


def _keys() -> Iterator[tuple[str, int]]:
    settings = get_settings()
    client = make_s3_client(settings)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"]


def count() -> dict[str, int]:
    objects = total = 0
    for _, size in _keys():
        objects += 1
        total += size
    return {"objects": objects, "bytes": total}


def archive() -> int:
    settings = get_settings()
    client = make_s3_client(settings)
    written = 0
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as tar:
        for key, size in _keys():
            body = client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
            info = tarfile.TarInfo(name=key)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
            written += 1
            assert size == len(body), key
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--archive", action="store_true")
    mode.add_argument("--count", action="store_true")
    args = parser.parse_args()
    if args.count:
        print(json.dumps(count()))
        return 0
    written = archive()
    print(f"archived {written} objects", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
