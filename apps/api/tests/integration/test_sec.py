"""M0.5 acceptance with recorded real SEC responses (tests/fixtures/sec, see manifest.json):
ticker map, filing index, XBRL facts with accession links, restatement versions and as_of(),
idempotent reruns and conflict counting. Runs the real jobs through IngestionRunner against
the throwaway test database; HTTP is served from the fixtures."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from autotrading.adapters.sec.acceptance import EASTERN, header_url
from autotrading.adapters.sec.company import companyfacts_url, submissions_url
from autotrading.adapters.sec.concepts import TAXONOMIES
from autotrading.adapters.sec.refresh import company_ciks, create_company_runs
from autotrading.config_sync import load_sources, sync_sources
from autotrading.db.models import (
    Entity,
    Filing,
    FinancialFact,
    Identifier,
    IngestionRun,
    Instrument,
    Source,
)
from autotrading.infra.object_store import make_s3_client
from autotrading.infra.redis_client import make_redis
from autotrading.ingestion.job import Window
from autotrading.ingestion.rate_limit import TokenBucketLimiter
from autotrading.ingestion.raw_store import RawPayloadStore
from autotrading.ingestion.runner import IngestionRunner
from autotrading.repositories.facts import FinancialFactRepository
from autotrading.settings import get_settings
from tests.sec_replay import FIXTURES, OVERRIDES, VerifyingCompany, recorded_registry

pytestmark = pytest.mark.integration

CIK = "0000320193"
ORIGINAL_10K = "0001193125-09-214859"  # accepted 2009-10-27 20:18:29 UTC
RESTATED_10KA = "0001193125-10-012091"  # accepted 2010-01-25 21:25:58 UTC
FY2008 = (date(2007, 9, 30), date(2008, 9, 27))


@pytest.fixture(scope="module")
def sessions(engine: Engine) -> sessionmaker[Session]:
    settings = get_settings()
    with Session(engine) as session:
        sync_sources(session, load_sources(settings.resolved_config_dir() / "sources.yaml"))
        source = session.get_one(Source, "sec_edgar")
        source.rate_limit_per_second, source.rate_limit_burst = 100, 100  # type: ignore[assignment]
        session.commit()
    return sessionmaker(engine)


@pytest.fixture(scope="module")
def runner(sessions: sessionmaker[Session]) -> Iterator[IngestionRunner]:
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    yield IngestionRunner(
        sessions,
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        recorded_registry(),
    )
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


def day_window(day: int) -> Window:
    start = datetime(2026, 10, day, tzinfo=UTC)
    return Window(start=start, end=start + timedelta(days=1))


def run(runner: IngestionRunner, job: str, params: dict[str, Any], window: Window) -> IngestionRun:
    run_id = runner.create_run(job, params, window)
    runner.execute(run_id)
    with runner.sessions() as session:
        return session.get_one(IngestionRun, run_id)


@pytest.fixture(scope="module")
def tickers_run(runner: IngestionRunner) -> IngestionRun:
    return run(runner, "sec.tickers", {"tickers": ["AAPL", "MSFT"]}, day_window(1))


@pytest.fixture(scope="module")
def company_run(runner: IngestionRunner, tickers_run: IngestionRun) -> IngestionRun:
    return run(runner, "sec.company", {"cik": CIK}, day_window(1))


@pytest.fixture(scope="module")
def apple(sessions: sessionmaker[Session], company_run: IngestionRun) -> UUID:
    with sessions() as session:
        identifier = session.scalars(
            select(Identifier).where(Identifier.id_type == "cik", Identifier.id_value == CIK)
        ).one()
        assert identifier.entity_id is not None
        return identifier.entity_id


def count(session: Session, model: Any, *where: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


# ---------- tickers ----------


def test_tickers_map_to_entities_instruments_and_ciks(
    sessions: sessionmaker[Session], tickers_run: IngestionRun
) -> None:
    assert tickers_run.status == "succeeded"
    assert tickers_run.rows_inserted == 2 * 4  # entity, CIK, instrument, ticker per company
    with sessions() as session:
        ticker = session.scalars(
            select(Identifier).where(Identifier.id_type == "ticker", Identifier.id_value == "AAPL")
        ).one()
        assert ticker.instrument_id is not None
        instrument = session.get_one(Instrument, ticker.instrument_id)
        assert (instrument.primary_exchange, instrument.currency) == ("XNAS", "USD")
        assert instrument.entity_id is not None
        assert session.get_one(Entity, instrument.entity_id).name == "Apple Inc."
        assert ticker.valid_to is None and ticker.id_namespace == "sec"
        assert company_ciks(session, ["AAPL", "MSFT", "NOPE"]) == ["0000320193", "0000789019"]


def test_tickers_rerun_changes_nothing(runner: IngestionRunner, tickers_run: IngestionRun) -> None:
    again = run(runner, "sec.tickers", {"tickers": ["AAPL", "MSFT"]}, day_window(2))
    assert (again.status, again.rows_inserted, again.rows_unchanged) == ("succeeded", 0, 2)


def test_company_runs_follow_the_tickers_run_window(
    runner: IngestionRunner, sessions: sessionmaker[Session], tickers_run: IngestionRun
) -> None:
    run_ids = create_company_runs(runner, tickers_run.id)
    with sessions() as session:
        runs = [session.get_one(IngestionRun, run_id) for run_id in run_ids]
    assert [r.params for r in runs] == [{"cik": "0000320193"}, {"cik": "0000789019"}]
    assert all(
        (r.window_start, r.window_end) == (tickers_run.window_start, tickers_run.window_end)
        for r in runs
    )


# ---------- filings and facts ----------


def test_filing_index_is_stored_with_acceptance_times(
    sessions: sessionmaker[Session], apple: UUID, company_run: IngestionRun
) -> None:
    assert company_run.status == "succeeded"
    with sessions() as session:
        assert count(session, Filing, Filing.entity_id == apple) == 2260
        amended = session.scalars(
            select(Filing).where(Filing.accession_number == RESTATED_10KA)
        ).one()
    assert amended.form == "10-K/A"
    assert amended.accepted_at == datetime(2010, 1, 25, 21, 25, 58, tzinfo=UTC)
    assert (amended.published_at, amended.published_at_precision) == (amended.accepted_at, "exact")
    assert amended.source_url.endswith("/000119312510012091/0001193125-10-012091-index.htm")
    assert amended.ingestion_run_id == company_run.id


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE filings SET form = '10-K' WHERE accession_number = :accession",
        "DELETE FROM filings WHERE accession_number = :accession",
        "TRUNCATE filings",
    ],
)
def test_filings_are_append_only(engine: Engine, apple: UUID, statement: str) -> None:
    with engine.connect() as conn, pytest.raises(DBAPIError, match=r"append-only|TRUNCATE"):
        conn.execute(text(statement), {"accession": RESTATED_10KA})


def test_every_fact_links_to_its_accession_and_filing_url(
    sessions: sessionmaker[Session], apple: UUID
) -> None:
    with sessions() as session:
        facts = session.scalars(select(FinancialFact).where(FinancialFact.entity_id == apple)).all()
        filings = set(
            session.scalars(select(Filing.accession_number).where(Filing.entity_id == apple))
        )
    assert len(facts) > 1000
    for fact in facts:
        assert fact.accession_id in filings
        assert fact.source_url == (
            "https://www.sec.gov/Archives/edgar/data/320193/"
            f"{fact.accession_id.replace('-', '')}/{fact.accession_id}-index.htm"
        )
        assert fact.source_concept and fact.source_concept.split(":")[0] in TAXONOMIES
        assert fact.published_at_precision == "exact"
        assert fact.raw_payload_sha256 is not None and fact.source_tier == 1


def test_restated_value_has_two_versions_and_as_of_returns_the_original(
    sessions: sessionmaker[Session], apple: UUID
) -> None:
    with sessions() as session:
        versions = session.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.entity_id == apple,
                FinancialFact.metric_id == "net_income",
                FinancialFact.period_start == FY2008[0],
                FinancialFact.period_end == FY2008[1],
            )
            .order_by(FinancialFact.version)
        ).all()
        repo = FinancialFactRepository(session)

        def known_on(day: datetime) -> Decimal:
            (fact,) = [
                f
                for f in repo.as_of(known_at=day, entity_id=apple, metric_id="net_income")
                if (f.period_start, f.period_end) == FY2008
            ]
            return fact.value

        before = known_on(datetime(2010, 1, 25, 21, 0, tzinfo=UTC))  # 10-K/A not yet accepted
        after = known_on(datetime(2010, 1, 25, 21, 30, tzinfo=UTC))

    original, restated = versions
    assert (original.value, original.accession_id, original.restated_flag) == (
        Decimal("4834000000"),
        ORIGINAL_10K,
        False,
    )
    assert (restated.value, restated.accession_id, restated.restated_flag) == (
        Decimal("6119000000"),
        RESTATED_10KA,
        True,
    )
    assert (restated.supersedes_fact_id, restated.revision_reason) == (original.id, "restatement")
    assert (before, after) == (Decimal("4834000000"), Decimal("6119000000"))


def test_same_window_is_skipped_and_a_new_day_adds_nothing(
    runner: IngestionRunner, sessions: sessionmaker[Session], apple: UUID
) -> None:
    with sessions() as session:
        facts_before = count(session, FinancialFact, FinancialFact.entity_id == apple)
    skipped = run(runner, "sec.company", {"cik": CIK}, day_window(1))
    next_day = run(runner, "sec.company", {"cik": CIK}, day_window(2))
    with sessions() as session:
        facts_after = count(session, FinancialFact, FinancialFact.entity_id == apple)
    assert skipped.status == "skipped"
    # Re-reading the whole history, restatements included, is not a conflict.
    assert (next_day.status, next_day.rows_inserted, next_day.rows_conflicted) == (
        "succeeded",
        0,
        0,
    )
    assert next_day.rows_unchanged > 2260
    assert facts_after == facts_before


def test_conflicting_values_in_one_filing_are_counted_not_fatal(
    runner: IngestionRunner, sessions: sessionmaker[Session], apple: UUID
) -> None:
    data = json.loads((FIXTURES / f"companyfacts_CIK{CIK}.json").read_bytes())
    observations: list[dict[str, Any]] = data["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]
    latest = max(observations, key=lambda o: o["filed"])
    observations.append({**latest, "val": latest["val"] + 1})  # same filing, other value
    OVERRIDES[companyfacts_url(CIK)] = json.dumps(data).encode()
    try:
        result = run(runner, "sec.company", {"cik": CIK}, day_window(3))
    finally:
        OVERRIDES.clear()
    assert (result.status, result.rows_inserted, result.rows_conflicted) == ("succeeded", 0, 1)


def test_company_without_entity_fails_with_a_clear_error(runner: IngestionRunner) -> None:
    unknown = "0000000001"
    OVERRIDES[submissions_url(unknown)] = (FIXTURES / f"submissions_CIK{CIK}.json").read_bytes()
    try:
        run_id = runner.create_run("sec.company", {"cik": unknown}, day_window(4))
        with pytest.raises(LookupError, match=r"run sec\.tickers first"):
            runner.execute(run_id)
    finally:
        OVERRIDES.clear()


@pytest.fixture(scope="module")
def verifying_runner(sessions: sessionmaker[Session]) -> Iterator[IngestionRunner]:
    """Like `runner`, but sec.company checks new filings against their headers (production)."""
    settings = get_settings()
    s3 = make_s3_client(settings)
    bucket = f"raw-payloads-test-{uuid4().hex[:10]}"
    s3.create_bucket(Bucket=bucket)
    registry = recorded_registry()
    registry["sec.company"] = VerifyingCompany
    yield IngestionRunner(
        sessions,
        RawPayloadStore(s3, bucket),
        TokenBucketLimiter(make_redis(settings), prefix=f"test-ratelimit-{uuid4().hex[:8]}"),
        registry,
    )
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


# True acceptance 2026-10-06 16:05:00 New York (EDT) = 20:05:00 UTC.
NEW_TRUE = datetime(2026, 10, 6, 20, 5, tzinfo=UTC)


def with_new_filings(rows: list[tuple[str, str, datetime]], headers: dict[str, datetime]) -> None:
    """Serve Apple's recorded submissions plus synthetic new filings (accession, form, JSON
    acceptance), and EDGAR headers for the accessions in `headers`."""
    data = json.loads((FIXTURES / f"submissions_CIK{CIK}.json").read_bytes())
    recent = data["filings"]["recent"]
    template = {column: values[0] for column, values in recent.items()}
    for accession, form, accepted in rows:
        row = {
            **template,
            "accessionNumber": accession,
            "form": form,
            "filingDate": "2026-10-06",
            "acceptanceDateTime": accepted.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "items": "",
        }
        for column, values in recent.items():
            values.insert(0, row[column])
    OVERRIDES[submissions_url(CIK)] = json.dumps(data).encode()
    for accession, accepted in headers.items():
        wall = accepted.astimezone(EASTERN).strftime("%Y%m%d%H%M%S")
        OVERRIDES[header_url(CIK, accession)] = f"<ACCEPTANCE-DATETIME>{wall}\n".encode()


def test_new_filings_take_their_time_from_the_edgar_header(
    verifying_runner: IngestionRunner, sessions: sessionmaker[Session], apple: UUID
) -> None:
    """SEC's 2026-10-06 bug replayed on a new 10-Q (JSON 4 h late); a new 424B2 whose JSON is
    right; a new Form 4 whose header is missing is stored date-only."""
    late_10q, right_424, no_header_4 = (
        "0000320193-26-900001",
        "0000320193-26-900002",
        "0000320193-26-900003",
    )
    with_new_filings(
        [
            (late_10q, "10-Q", NEW_TRUE + timedelta(hours=4)),
            (right_424, "424B2", NEW_TRUE),
            (no_header_4, "4", NEW_TRUE),
        ],
        headers={late_10q: NEW_TRUE, right_424: NEW_TRUE},
    )
    try:
        result = run(verifying_runner, "sec.company", {"cik": CIK}, day_window(20))
    finally:
        OVERRIDES.clear()
    assert (result.status, result.rows_inserted, result.rows_conflicted) == ("succeeded", 3, 0)
    assert result.notes == [
        "2 new filings timed from their EDGAR headers; 1 JSON times were late by the New York "
        "offset; 1 other new filings beyond 200 per run stored date-only"
    ]
    with sessions() as session:
        stored = {
            f.accession_number: (f.accepted_at, f.published_at, f.published_at_precision)
            for f in session.scalars(
                select(Filing).where(
                    Filing.accession_number.in_([late_10q, right_424, no_header_4])
                )
            )
        }
    assert stored[late_10q] == (NEW_TRUE, NEW_TRUE, "exact")
    assert stored[right_424] == (NEW_TRUE, NEW_TRUE, "exact")
    assert stored[no_header_4][0] is None
    assert stored[no_header_4][2] == "day"


def test_a_new_8k_without_header_fails_the_run_and_stores_nothing(
    verifying_runner: IngestionRunner, sessions: sessionmaker[Session], apple: UUID
) -> None:
    with sessions() as session:
        filings_before = session.scalar(select(func.count()).select_from(Filing))
    with_new_filings([("0000320193-26-900004", "8-K", NEW_TRUE)], headers={})
    try:
        run_id = verifying_runner.create_run("sec.company", {"cik": CIK}, day_window(21))
        with pytest.raises(RuntimeError, match="no EDGAR header acceptance time for 8-K"):
            verifying_runner.execute(run_id)
    finally:
        OVERRIDES.clear()
    with sessions() as session:
        failed = session.get_one(IngestionRun, run_id)
        assert (failed.status, failed.error_class) == ("failed", "AcceptanceCheckError")
        assert session.scalar(select(func.count()).select_from(Filing)) == filings_before
