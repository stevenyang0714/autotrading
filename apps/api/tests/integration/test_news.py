"""M0.8 acceptance on recorded real news (tests/fixtures/news, manifest.json): every item links
to its original URL; syndicated copies of one story share a duplicate_group_id; no stored
field or stored payload holds article text. Also: reruns add nothing, items are append-only,
companies are matched by rule, and the API filters by company, source, tier and time.
Uses its own migrated database."""

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.alpaca.refresh import universe
from autotrading.adapters.news.config import feeds
from autotrading.adapters.sec.tickers import SecTickersJob
from autotrading.config_sync import load_sources, sync_sources
from autotrading.db.models import IngestionRun, NewsItem, NewsMention, RawPayload, Source
from autotrading.domain.news import SNIPPET_MAX_CHARS, canonical_url
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.main import create_app
from autotrading.settings import get_settings
from tests import news_replay, sec_replay
from tests.integration.conftest import alembic_config
from tests.news_replay import MANIFEST, SYNDICATION_CASE

pytestmark = pytest.mark.integration

WINDOW = Window(start=datetime(2026, 10, 6, tzinfo=UTC), end=datetime(2026, 10, 7, tzinfo=UTC))
NEWS_SOURCES = ["gdelt", *feeds()]


class OkChecker:
    def core(self) -> dict[str, Any]:
        return {}

    def background(self) -> dict[str, Any]:
        return {}


@pytest.fixture(scope="module")
def engine(database_factory: Callable[[], URL]) -> Iterator[Engine]:
    url = database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    config = get_settings().resolved_config_dir()
    with Session(engine) as session:
        sync_sources(session, load_sources(config / "sources.yaml"))
        for source_id in ["sec_edgar", *NEWS_SOURCES]:
            source = session.get_one(Source, source_id)
            source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def bucket() -> Iterator[str]:
    s3 = make_s3_client(get_settings())
    name = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=name)
    yield name
    for obj in s3.list_objects_v2(Bucket=name).get("Contents", []):
        s3.delete_object(Bucket=name, Key=obj["Key"])
    s3.delete_bucket(Bucket=name)


@pytest.fixture(scope="module")
def runner(engine: Engine, bucket: str) -> IngestionRunner:
    settings = get_settings()
    registry = news_replay.register_recorded(sec_replay.recorded_registry(), fixture=False)
    return IngestionRunner(
        sessionmaker(engine),
        RawPayloadStore(make_s3_client(settings), bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        registry,
    )


@pytest.fixture(scope="module")
def runs(runner: IngestionRunner) -> list[IngestionRun]:
    symbols, etfs = universe(get_settings().resolved_config_dir())
    equities = [s for s in symbols if s not in etfs]
    tickers = runner.create_run(
        SecTickersJob.name, {"tickers": equities, "predecessors": {}}, WINDOW
    )
    runner.execute(tickers)
    run_ids = news_replay.replay(runner, WINDOW)
    with runner.sessions() as session:
        return [session.get_one(IngestionRun, run_id) for run_id in run_ids]


@pytest.fixture(scope="module")
def client(engine: Engine, runs: list[IngestionRun]) -> Iterator[TestClient]:
    with TestClient(
        create_app(health_checker=OkChecker(), sessions=sessionmaker(engine))
    ) as client:
        yield client


# ---------- ingestion and acceptance ----------


def test_every_run_succeeds_and_stores_news(runs: list[IngestionRun], engine: Engine) -> None:
    assert [r.status for r in runs] == ["succeeded"] * len(MANIFEST["runs"])
    with Session(engine) as session:
        by_source = dict(
            session.execute(
                select(NewsItem.source_id, func.count()).group_by(NewsItem.source_id)
            ).all()
        )
    assert by_source.get("gdelt", 0) > 0
    assert set(feeds()) <= set(by_source)  # every feed contributed items


def test_every_item_links_to_its_original_url(engine: Engine, runs: list[IngestionRun]) -> None:
    # M0.8 acceptance 1.
    with Session(engine) as session:
        items = session.scalars(select(NewsItem)).all()
    assert items
    assert all(item.url.startswith(("https://", "http://")) for item in items)
    assert all(item.canonical_url.startswith("https://") for item in items)
    assert len({item.canonical_url for item in items}) == len(items)


def test_syndicated_copies_share_a_duplicate_group(
    engine: Engine, runs: list[IngestionRun]
) -> None:
    # M0.8 acceptance 2, on a real headline carried by several sites (manifest.json).
    urls = SYNDICATION_CASE["canonical_urls"]
    with Session(engine) as session:
        rows = session.execute(
            select(
                NewsItem.canonical_url, NewsItem.duplicate_group_id, NewsItem.publisher_domain
            ).where(NewsItem.canonical_url.in_(urls))
        ).all()
    assert len(rows) == len(urls) >= 2
    assert len({group for _, group, _ in rows}) == 1
    assert len({domain for _, _, domain in rows}) == len(urls)


def test_no_article_text_is_stored(engine: Engine, runs: list[IngestionRun], bucket: str) -> None:
    # M0.8 acceptance 3: titles and summaries are short, and stored feeds have no full text.
    with Session(engine) as session:
        longest_title, longest_snippet = session.execute(
            select(func.max(func.length(NewsItem.title)), func.max(func.length(NewsItem.snippet)))
        ).one()
        keys = session.scalars(
            select(RawPayload.object_key).where(RawPayload.source_id.in_(NEWS_SOURCES))
        ).all()
    assert longest_title <= 500 and longest_snippet <= SNIPPET_MAX_CHARS
    s3 = make_s3_client(get_settings())
    assert keys
    for key in keys:
        content = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        assert b"purl.org/rss/1.0/modules/content" not in content, key
        assert b"content:encoded" not in content, key


def test_the_database_refuses_long_text(engine: Engine, runs: list[IngestionRun]) -> None:
    with Session(engine) as session:
        item = session.scalars(select(NewsItem).limit(1)).one()
    with engine.connect() as conn, pytest.raises(DBAPIError, match="snippet_length"):
        conn.execute(
            text(
                "INSERT INTO news_items (url, canonical_url, title, title_key, publisher, "
                "publisher_domain, snippet, language, kind, time_basis, duplicate_group_id, "
                "data_mode, source_id, source_tier, source_url, published_at, "
                "published_at_precision, ingested_at, effective_from, as_of, license_status, "
                "confidence) SELECT 'https://e.st/x', 'https://e.st/x', 't', 't', 'p', 'e.st', "
                "repeat('x', 301), 'en', 'article', 'publisher', gen_random_uuid(), 'live', "
                "source_id, source_tier, source_url, published_at, published_at_precision, "
                "ingested_at, effective_from, as_of, license_status, confidence "
                "FROM news_items WHERE id = :id"
            ),
            {"id": item.id},
        )


def test_a_rerun_adds_nothing(runner: IngestionRunner, runs: list[IngestionRun]) -> None:
    window = Window(start=datetime(2026, 10, 7, tzinfo=UTC), end=datetime(2026, 10, 8, tzinfo=UTC))
    rerun_ids = news_replay.replay(runner, window)
    with runner.sessions() as session:
        reruns = [session.get_one(IngestionRun, run_id) for run_id in rerun_ids]
    assert [(r.status, r.rows_inserted) for r in reruns] == [("succeeded", 0)] * len(rerun_ids)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE news_items SET title = 'x'",
        "DELETE FROM news_items",
        "TRUNCATE news_items",
        "UPDATE news_mentions SET ticker = 'X'",
        "DELETE FROM news_mentions",
    ],
)
def test_news_is_append_only(engine: Engine, runs: list[IngestionRun], statement: str) -> None:
    with engine.connect() as conn, pytest.raises(DBAPIError, match=r"append-only|TRUNCATE"):
        conn.execute(text(statement))


def test_companies_are_matched_by_rule(engine: Engine, runs: list[IngestionRun]) -> None:
    with Session(engine) as session:
        issuer = session.execute(
            select(NewsMention.ticker, NewsMention.rule, NewsMention.confidence)
            .join(NewsItem, NewsItem.id == NewsMention.news_item_id)
            .where(NewsItem.source_id == "apple_newsroom")
        ).all()
        unlinked_gdelt = session.scalar(
            select(func.count())
            .select_from(NewsItem)
            .where(
                NewsItem.source_id == "gdelt",
                NewsItem.id.not_in(select(NewsMention.news_item_id)),
            )
        )
        bare_low = session.scalar(
            select(func.count())
            .select_from(NewsMention)
            .where(NewsMention.ticker == "LOW", NewsMention.rule == "bare_ticker")
        )
    assert issuer and {(t, r) for t, r, _ in issuer} == {("AAPL", "feed_issuer")}
    assert unlinked_gdelt == 0  # GDELT articles are kept only when a company is named
    assert bare_low == 0


def test_gdelt_items_keep_their_publisher_tier_and_first_seen_time(
    engine: Engine, runs: list[IngestionRun]
) -> None:
    with Session(engine) as session:
        tiers = set(
            session.scalars(
                select(NewsItem.source_tier).where(NewsItem.source_id == "gdelt").distinct()
            )
        )
        bases = set(
            session.scalars(
                select(NewsItem.time_basis).where(NewsItem.source_id == "gdelt").distinct()
            )
        )
    # The approved lists apply (Tier 2 outlets, Tier 3 specialists); the rest stay Tier 4.
    assert tiers <= {1, 2, 3, 4} and {2, 3, 4} <= tiers
    assert bases == {"first_seen"}


# ---------- API ----------


def test_news_api_collapses_copies(client: TestClient) -> None:
    body = client.get("/news", params={"limit": 100}).json()
    assert body["story_count"] < body["article_count"]
    assert body["attribution_url"] == "https://www.gdeltproject.org/"
    wanted = set(SYNDICATION_CASE["canonical_urls"])
    (story,) = [
        g
        for g in body["groups"]
        if wanted & {canonical_url(i["url"]) for i in [g["lead"], *g["others"]]}
    ]
    copies = {canonical_url(i["url"]) for i in [story["lead"], *story["others"]]}
    assert wanted <= copies
    assert story["article_count"] == len(story["others"]) + 1 == len(copies)
    assert story["publisher_count"] >= 2


def test_news_api_filters(client: TestClient) -> None:
    sec = client.get("/news", params={"source": "sec_press"}).json()
    assert sec["groups"] and {g["lead"]["source_id"] for g in sec["groups"]} == {"sec_press"}
    official = client.get("/news", params={"max_tier": 1, "limit": 100}).json()
    assert official["groups"] and all(g["best_tier"] == 1 for g in official["groups"])
    apple = client.get("/news", params={"ticker": "aapl", "limit": 100}).json()
    assert apple["ticker"] == "AAPL"
    assert apple["groups"] and all("AAPL" in g["tickers"] for g in apple["groups"])
    assert {s["id"] for s in apple["sources"]} >= set(NEWS_SOURCES)


def test_news_api_filters_by_kind(client: TestClient) -> None:
    issuer = client.get("/news", params={"ticker": "AAPL", "kind": "press_release"}).json()
    assert issuer["kinds"] == ["press_release"]
    assert issuer["groups"] and {g["lead"]["source_id"] for g in issuer["groups"]} == {
        "apple_newsroom"
    }
    media = client.get("/news", params={"kind": "article,official", "limit": 100}).json()
    assert {g["lead"]["kind"] for g in media["groups"]} <= {"article", "official"}
    assert client.get("/news", params={"kind": "blog"}).status_code == 422


def test_blocked_sites_are_not_stored(engine: Engine, runs: list[IngestionRun]) -> None:
    with Session(engine) as session:
        blocked = session.scalar(
            select(func.count())
            .select_from(NewsItem)
            .where(NewsItem.publisher_domain.like("%dhal3.com"))
        )
    assert blocked == 0


def test_news_as_known_at_a_time(client: TestClient, engine: Engine) -> None:
    urls = SYNDICATION_CASE["canonical_urls"]
    with Session(engine) as session:
        first = session.scalar(
            select(func.min(NewsItem.published_at)).where(NewsItem.canonical_url.in_(urls))
        )
    assert first is not None

    def story_urls(known_at: datetime) -> set[str]:
        body = client.get(
            "/news", params={"known_at": known_at.isoformat(), "limit": 100, "source": "gdelt"}
        ).json()
        return {item["url"] for g in body["groups"] for item in [g["lead"], *g["others"]]}

    before, after = story_urls(first - timedelta(seconds=1)), story_urls(first + timedelta(days=3))
    with Session(engine) as session:
        raw_urls = set(
            session.scalars(select(NewsItem.url).where(NewsItem.canonical_url.in_(urls)))
        )
    assert not (raw_urls & before)
    assert raw_urls <= after


def test_data_health_schedules_news(client: TestClient) -> None:
    sources = {s["id"]: s for s in client.get("/data-health").json()["sources"]}
    for source_id in NEWS_SOURCES:
        assert sources[source_id]["freshness"] in {"fresh", "stale"}, source_id
        assert sources[source_id]["next_refresh_at"] is not None, source_id


# ---------- web fixtures (opt-in recorder) ----------


@pytest.mark.skipif(
    not os.environ.get("RECORD_WEB_FIXTURES"),
    reason="recorder: set RECORD_WEB_FIXTURES=1 to refresh apps/web/tests/fixtures/api",
)
def test_record_web_fixtures(client: TestClient) -> None:
    target = Path(__file__).resolve().parents[3] / "web" / "tests" / "fixtures" / "api"
    recorded: tuple[tuple[str, dict[str, str | int]], ...] = (
        ("news", {"limit": 30}),
        ("news-nvda", {"ticker": "NVDA", "limit": 8}),
        ("news-nvda-announcements", {"ticker": "NVDA", "kind": "press_release", "limit": 6}),
        ("news-nvda-coverage", {"ticker": "NVDA", "kind": "article,official", "limit": 6}),
    )
    for name, params in recorded:
        response = client.get("/news", params=params)
        assert response.status_code == 200
        record = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "recorded_from": "recorded GDELT and feed fixtures replayed into the integration "
            "test database (tests/integration/test_news.py)",
            "endpoint": "/news",
            "params": params,
            "response": response.json(),
        }
        (target / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
