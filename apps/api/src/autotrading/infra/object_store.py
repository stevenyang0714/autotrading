"""S3-compatible object store (Silo locally, ADR-011): client, bucket bootstrap, health probe."""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from autotrading.infra.probes import PROBE_TIMEOUT_SECONDS, ProbeResult, run_probe
from autotrading.settings import Settings

if TYPE_CHECKING:
    # Type stubs are a dev dependency; never import them at runtime.
    from mypy_boto3_s3 import S3Client


def make_s3_client(settings: Settings) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1",
        config=Config(
            connect_timeout=PROBE_TIMEOUT_SECONDS,
            read_timeout=PROBE_TIMEOUT_SECONDS,
            retries={"max_attempts": 1},
            s3={"addressing_style": "path"},
        ),
    )


def ensure_bucket(client: S3Client, bucket: str) -> None:
    """Create the bucket if it does not exist. Safe to call repeatedly."""
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
            raise
        client.create_bucket(Bucket=bucket)


def probe_object_store(client: S3Client, bucket: str) -> ProbeResult:
    def check() -> str:
        client.head_bucket(Bucket=bucket)
        return f"bucket {bucket} exists"

    return run_probe(check)
