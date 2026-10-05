"""Contract between the ingestion runner and provider adapters (M0.5+).

An adapter subclasses IngestionJob, registers it with @register_job, and implements:
- fetch(ctx): download raw responses, calling ctx.acquire() before every provider request;
- store(ctx): parse the stored payloads and write facts through the repositories.
"""

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Window:
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True)
class FetchedPayload:
    content: bytes
    content_type: str
    source_url: str
    fetched_at: datetime


@dataclass(frozen=True)
class StoredPayload:
    object_key: str
    sha256: str
    content: bytes
    content_type: str
    source_url: str
    fetched_at: datetime


@dataclass(frozen=True)
class FetchContext:
    run_id: UUID
    acquire: Callable[[], None]  # rate limiter: call before every provider request


@dataclass(frozen=True)
class StoreContext:
    session: Session
    run_id: UUID
    payloads: list[StoredPayload]


@dataclass(frozen=True)
class StoreResult:
    inserted: int
    unchanged: int


class IngestionJob(ABC):
    source_id: ClassVar[str]
    name: ClassVar[str]

    def __init__(self, params: dict[str, Any], window: Window) -> None:
        self.params = params
        self.window = window

    @abstractmethod
    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]: ...

    @abstractmethod
    def store(self, ctx: StoreContext) -> StoreResult: ...


JobRegistry = dict[str, type[IngestionJob]]
JOB_REGISTRY: JobRegistry = {}


def register_job[J: type[IngestionJob]](job: J, registry: JobRegistry | None = None) -> J:
    target = JOB_REGISTRY if registry is None else registry
    if job.name in target and target[job.name] is not job:
        raise ValueError(f"ingestion job {job.name!r} is already registered")
    target[job.name] = job
    return job


def idempotency_key(source_id: str, job: str, params: dict[str, Any], window: Window) -> str:
    """sha256 over source, job, canonical params and window: equal inputs, equal key."""
    canonical = json.dumps(
        {
            "source": source_id,
            "job": job,
            "params": params,
            "window": [
                window.start.isoformat() if window.start else None,
                window.end.isoformat() if window.end else None,
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
