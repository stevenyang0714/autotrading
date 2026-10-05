"""Raw provider responses, content-addressed in the object store (ADR-007, ADR-011)."""

import base64
import hashlib
from typing import TYPE_CHECKING
from uuid import UUID

from botocore.exceptions import ClientError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from autotrading.db.models import RawPayload
from autotrading.ingestion.job import FetchedPayload, StoredPayload

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def object_key(source_id: str, sha256: str) -> str:
    return f"raw/{source_id}/{sha256[:2]}/{sha256}"


class RawPayloadStore:
    def __init__(self, s3: "S3Client", bucket: str) -> None:
        self._s3 = s3
        self._bucket = bucket

    def put(self, source_id: str, payload: FetchedPayload) -> StoredPayload:
        """Upload unless an object with the same content already exists."""
        sha = hashlib.sha256(payload.content).hexdigest()
        key = object_key(source_id, sha)
        if not self._exists(key):
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=payload.content,
                ContentType=payload.content_type,
                ChecksumSHA256=_b64_sha256(payload.content),
            )
        return StoredPayload(
            object_key=key,
            sha256=sha,
            content=payload.content,
            content_type=payload.content_type,
            source_url=payload.source_url,
            fetched_at=payload.fetched_at,
        )

    def _exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True


def record_payloads(
    session: Session, source_id: str, run_id: UUID, payloads: list[StoredPayload]
) -> None:
    """One metadata row per (source, sha256); later runs that fetch the same bytes reuse it."""
    for payload in payloads:
        session.execute(
            insert(RawPayload)
            .values(
                source_id=source_id,
                ingestion_run_id=run_id,
                object_key=payload.object_key,
                sha256=payload.sha256,
                size_bytes=len(payload.content),
                content_type=payload.content_type,
                source_url=payload.source_url,
                fetched_at=payload.fetched_at,
            )
            .on_conflict_do_nothing(index_elements=["source_id", "sha256"])
        )


def _b64_sha256(content: bytes) -> str:
    return base64.b64encode(hashlib.sha256(content).digest()).decode()
