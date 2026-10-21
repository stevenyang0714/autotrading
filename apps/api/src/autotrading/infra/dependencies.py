"""Live connections to the local stack, shared by the API process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from redis import Redis
from sqlalchemy import Engine

from autotrading.infra.db import make_engine, make_probe_engine, probe_database
from autotrading.infra.heartbeat import probe_heartbeat
from autotrading.infra.object_store import make_s3_client, probe_object_store
from autotrading.infra.probes import ProbeResult
from autotrading.infra.redis_client import make_redis, probe_redis
from autotrading.settings import Settings

if TYPE_CHECKING:
    # Type stubs are a dev dependency; never import them at runtime.
    from mypy_boto3_s3 import S3Client


@dataclass
class Dependencies:
    engine: Engine
    probe_engine: Engine
    redis: Redis
    s3: S3Client
    bucket: str

    @classmethod
    def from_settings(cls, settings: Settings) -> Dependencies:
        return cls(
            engine=make_engine(settings),
            probe_engine=make_probe_engine(settings),
            redis=make_redis(settings),
            s3=make_s3_client(settings),
            bucket=settings.s3_bucket,
        )

    def core(self) -> dict[str, ProbeResult]:
        return {
            "database": probe_database(self.probe_engine),
            "redis": probe_redis(self.redis),
            "object_store": probe_object_store(self.s3, self.bucket),
        }

    def background(self) -> dict[str, ProbeResult]:
        return {
            "worker": probe_heartbeat(self.redis, "worker"),
            "scheduler": probe_heartbeat(self.redis, "scheduler"),
            "queue": probe_heartbeat(self.redis, "queue"),
        }

    def close(self) -> None:
        self.engine.dispose()
        self.probe_engine.dispose()
        self.redis.close()
