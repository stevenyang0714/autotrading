"""News rules (M0.8, ADR-018): canonical URLs, titles, duplicate groups, summaries, publisher
tiers, company mentions; full-text stripping; the news HTTP client; interval schedules."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx
import pytest

from autotrading.adapters.news.client import (
    FETCH_TIME_BUDGET_SECONDS,
    TIMEOUT_SECONDS,
    NewsClient,
    NewsRequestError,
)
from autotrading.adapters.news.gdelt import GdeltJob, articles, seen_at
from autotrading.adapters.news.rss import parse_feed, strip_full_text
from autotrading.domain.news import (
    RIGHT_QUOTE,
    SNIPPET_MAX_CHARS,
    Company,
    GroupCandidate,
    PublisherTiers,
    canonical_url,
    company_names,
    duplicate_group,
    find_mentions,
    normalize_title,
    short_company_name,
    snippet,
    title_similarity,
)
from autotrading.ingestion.job import RUN_TIME_LIMIT_SECONDS, FetchContext, Window
from autotrading.ingestion.schedule import IntervalSchedule

T0 = datetime(2026, 10, 2, 8, 15, tzinfo=UTC)
FEEDS = Path(__file__).resolve().parents[1] / "fixtures" / "news"


# ---------- URLs and titles ----------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.pr.com:443/press-release/980230", "https://pr.com/press-release/980230"),
        ("http://m.example.com/a/b/amp/?utm_source=x&id=2#top", "https://example.com/a/b?id=2"),
        ("https://example.com/story/?fbclid=abc", "https://example.com/story"),
        ("https://example.com/?b=2&a=1", "https://example.com/?a=1&b=2"),
    ],
)
def test_canonical_url(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


def test_titles_lose_a_trailing_publisher_name() -> None:
    # Real GDELT titles (2026-10-02).
    assert (
        normalize_title("Bond swings rattle stock markets around the world | The Arkansas Democrat")
        == "bond swings rattle stock markets around the world"
    )
    assert normalize_title("Nvidia unveils record $150 billion buyback increase") == (
        "nvidia unveils record 150 billion buyback increase"
    )
    # A short title keeps its last part: there is no headline left without it.
    assert normalize_title("Markets - Reuters") == "markets reuters"


def test_title_similarity_is_word_overlap() -> None:
    a = normalize_title("Nvidia unveils record $150 billion buyback increase")
    b = normalize_title("Nvidia unveils record $150bn buyback increase - Reuters")
    assert title_similarity(a, a) == 1.0
    assert 0 < title_similarity(a, b) < 0.85


# ---------- duplicate groups ----------


def candidate(
    title: str, published: datetime, url: str = "", domain: str = "texasguardian.com"
) -> GroupCandidate:
    group = uuid4()
    return GroupCandidate(
        group, group, url or f"https://x.com/{group}", normalize_title(title), published, domain
    )


def test_copies_of_one_headline_join_the_first_group() -> None:
    first = candidate("Nvidia unveils record $150 billion buyback increase", T0)
    group = duplicate_group(
        canonical="https://pittsburghstar.com/news/1",
        title_key=normalize_title("Nvidia unveils record $150 billion buyback increase"),
        published_at=T0 + timedelta(minutes=15),
        domain="pittsburghstar.com",
        existing=[first],
    )
    assert group == first.group_id


def test_same_url_is_the_same_article_whatever_the_title() -> None:
    first = candidate("Something", T0, url="https://example.com/a")
    assert (
        duplicate_group(
            canonical="https://example.com/a",
            title_key="other words entirely here",
            published_at=T0 + timedelta(days=30),
            domain="example.com",
            existing=[first],
        )
        == first.group_id
    )


@pytest.mark.parametrize(
    ("title", "published"),
    [
        ("Nvidia unveils record $150 billion buyback increase", T0 + timedelta(hours=73)),
        ("Nvidia shares fall after record buyback increase", T0),  # a different story
        ("Nvidia buyback", T0),  # too short to group on the title
    ],
)
def test_no_group_outside_the_rules(title: str, published: datetime) -> None:
    first = candidate("Nvidia unveils record $150 billion buyback increase", T0)
    assert (
        duplicate_group(
            canonical="https://example.org/new",
            title_key=normalize_title(title),
            published_at=published,
            domain="example.org",
            existing=[first],
        )
        is None
    )


def test_one_site_reposting_the_same_headline_is_one_story() -> None:
    # Real GDELT data (2026-10-02): a classifieds site posted one headline many times.
    title = "For Sale ( 10 Pieces ) New Apple iPhone Duo Original 256GB Unlocked $18 , 990CAD"
    first = candidate(title, T0, domain="dhal3.com")
    assert (
        duplicate_group(
            canonical="https://dhal3.com/vb/showthread.php?p=2",
            title_key=normalize_title(title),
            published_at=T0 + timedelta(hours=2),
            domain="dhal3.com",
            existing=[first],
        )
        == first.group_id
    )


def test_one_sites_series_of_similar_titles_stays_apart() -> None:
    # Real White House titles (2026-09): one order per product, near-identical wording.
    stem = (
        "Excluding Certain Canadian Products from Importation into the United States in "
        "Response to Continued Discrimination Against the Commerce of the United States with "
        "Respect to "
    )
    dairy = candidate(stem + "Dairy", T0, domain="whitehouse.gov")
    key = normalize_title(stem + "Motor Vehicles")
    assert title_similarity(dairy.title_key, key) >= 0.85
    assert (
        duplicate_group(
            canonical="https://whitehouse.gov/presidential-actions/motor-vehicles",
            title_key=key,
            published_at=T0,
            domain="whitehouse.gov",
            existing=[dairy],
        )
        is None
    )


# ---------- summaries ----------


def test_wordpress_footers_are_dropped() -> None:
    # Real Microsoft feed summary shape (2026-10-05).
    text = (
        "<p>The post How Power Platform helps businesses build AI into existing apps "
        "appeared first on Source.</p>"
    )
    assert snippet(text) is None
    assert snippet("<p>A real summary.</p> The post X appeared first on Meta.") == "A real summary."


def test_snippets_are_short_plain_text() -> None:
    assert snippet("<p>Hello &amp; <b>world</b></p>") == "Hello & world"
    long = snippet("<p>" + "word " * 200 + "</p>")
    assert long is not None and len(long) <= SNIPPET_MAX_CHARS and long.endswith("…")
    assert snippet("   ") is None and snippet(None) is None


# ---------- publisher tiers ----------


def test_blocked_publishers() -> None:
    tiers = PublisherTiers({}, (".gov",), 4, frozenset({"dhal3.com"}))
    assert tiers.is_blocked("dhal3.com") and tiers.is_blocked("www.dhal3.com")
    assert not tiers.is_blocked("notdhal3.com")


def test_publisher_tiers_by_domain() -> None:
    tiers = PublisherTiers({"reuters.com": (2, "Reuters")}, (".gov",), 4)
    assert tiers.lookup("uk.reuters.com") == (2, "Reuters")
    assert tiers.lookup("www.sec.gov") == (1, None)
    assert tiers.lookup("texasguardian.com") == (4, None)
    assert tiers.lookup("notreuters.com") == (4, None)


# ---------- company mentions ----------

COMPANIES = [
    Company("AAPL", company_names("Apple Inc.", ["Apple"]), True),
    Company(
        "META", company_names("Meta Platforms, Inc.", ["Meta", "Meta Platforms", "Facebook"]), True
    ),
    Company("LOW", company_names("LOWES COMPANIES INC", ["Lowe's", "Lowes"]), False),
    Company("NVDA", company_names("NVIDIA CORP", ["Nvidia", "NVIDIA"]), True),
]


def mentions(title: str) -> list[tuple[str, str, str]]:
    return [(m.ticker, m.rule, m.matched_text) for m in find_mentions(title, COMPANIES)]


def test_names_and_tickers_in_titles() -> None:
    assert mentions("Nvidia unveils record $150 billion buyback increase") == [
        ("NVDA", "company_name", "Nvidia")
    ]
    assert mentions("Apple's iPhone sales; $NVDA up") == [
        ("NVDA", "exchange_ticker", "$NVDA"),
        ("AAPL", "company_name", "Apple's"),
    ]
    assert mentions("Shares of AAPL fall (NASDAQ: META)") == [
        ("META", "exchange_ticker", "NASDAQ: META"),
        ("AAPL", "bare_ticker", "AAPL"),
    ]
    assert mentions("Meta Platforms beats estimates") == [
        ("META", "company_name", "Meta Platforms")
    ]


def test_typographic_apostrophes_match() -> None:
    assert mentions(f"Lowe{RIGHT_QUOTE}s raises outlook") == [("LOW", "company_name", "Lowe's")]


@pytest.mark.parametrize(
    "title",
    [
        "LOW prices on apples this week",  # LOW is an ordinary word: no bare ticker
        "Meta-analysis finds an apple a day helps",  # hyphenated word, lower-case apple
        "Pineapple prices climb",
    ],
)
def test_ordinary_words_are_not_companies(title: str) -> None:
    assert mentions(title) == []


def test_company_names_from_sec_names() -> None:
    assert short_company_name("JPMORGAN CHASE & CO") == "JPMORGAN CHASE"
    assert short_company_name("Meta Platforms, Inc.") == "Meta"
    # All-caps SEC names never match a headline, so only aliases are used for them.
    assert company_names("NVIDIA CORP", ["Nvidia"]) == ("Nvidia",)
    assert company_names("Apple Inc.", ["Apple"]) == ("Apple",)


# ---------- feeds ----------

FULL_TEXT_FEED = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Example</title><language>en-US</language>
<item><title>A title</title><link>https://example.gov/a</link>
<pubDate>Mon, 05 Oct 2026 08:47:36 -0400</pubDate>
<description><![CDATA[<p>Short summary.</p>]]></description>
<content:encoded><![CDATA[<p>The whole article text.</p>]]></content:encoded></item>
</channel></rss>"""


def test_full_text_is_stripped_before_storage() -> None:
    stripped = strip_full_text(FULL_TEXT_FEED)
    assert b"whole article text" not in stripped and b"encoded" not in stripped
    assert strip_full_text(stripped) == stripped  # idempotent
    (entry,) = parse_feed(stripped, "https://example.gov/feed").entries
    assert (entry.title, entry.link, entry.summary) == (
        "A title",
        "https://example.gov/a",
        "Short summary.",
    )
    assert entry.published == datetime(2026, 10, 5, 12, 47, 36, tzinfo=UTC)


@pytest.mark.parametrize("name", sorted(p.name for p in FEEDS.glob("feed_*.xml")))
def test_recorded_feeds_are_stripped_and_stay_stable(name: str) -> None:
    # The recorded feeds are what the jobs stored; replay strips them again.
    content = (FEEDS / name).read_bytes()
    assert b"purl.org/rss/1.0/modules/content" not in content
    again = strip_full_text(content)
    assert strip_full_text(again) == again
    entries = parse_feed(again, "https://example.com/feed").entries
    assert entries and all(len(e.summary or "") <= SNIPPET_MAX_CHARS for e in entries)


def test_long_summaries_are_cut() -> None:
    feed = FULL_TEXT_FEED.replace(b"Short summary.", b"word " * 400)
    (entry,) = parse_feed(strip_full_text(feed), "https://example.gov/feed").entries
    assert entry.summary is not None and len(entry.summary) <= SNIPPET_MAX_CHARS


def test_gdelt_responses() -> None:
    assert articles(b"") == [] and articles(b"{}") == []
    assert articles(b'{"articles": [{"url": "https://a.com/x"}]}') == [{"url": "https://a.com/x"}]
    with pytest.raises(NewsRequestError, match="text, not JSON"):
        articles(b"Your search contained a phrase that was too short.")
    assert seen_at("20261002T104500Z") == datetime(2026, 10, 2, 10, 45, tzinfo=UTC)


# ---------- client ----------


def test_client_refuses_unconfigured_hosts() -> None:
    client = NewsClient(
        {"api.gdeltproject.org"}, transport=httpx.MockTransport(lambda _: httpx.Response(200))
    )
    with pytest.raises(NewsRequestError, match="not a configured news endpoint"):
        client.get("https://evil.example.com/feed", None, lambda: None)
    with pytest.raises(NewsRequestError, match="not a configured news endpoint"):
        client.get("http://api.gdeltproject.org/api/v2/doc/doc", None, lambda: None)


def test_client_retries_rate_limits_and_handles_not_modified() -> None:
    answers = iter([httpx.Response(429), httpx.Response(304)])
    sleeps: list[float] = []
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(answers)

    client = NewsClient(
        {"www.sec.gov"},
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        sec_user_agent="Name n@e.st",
    )
    since = datetime(2026, 10, 6, 5, 0, tzinfo=UTC)
    assert (
        client.get(
            "https://www.sec.gov/news/pressreleases.rss",
            None,
            lambda: None,
            if_modified_since=since,
        )
        is None
    )
    assert sleeps == [15.0]
    assert seen[0].headers["User-Agent"] == "Name n@e.st"
    assert seen[0].headers["If-Modified-Since"] == "Tue, 06 Oct 2026 05:00:00 GMT"


def test_only_sec_gets_the_sec_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"{}")

    client = NewsClient(
        {"api.gdeltproject.org"},
        transport=httpx.MockTransport(handler),
        sec_user_agent="Name n@e.st",
    )
    client.get("https://api.gdeltproject.org/api/v2/doc/doc", {"query": "x"}, lambda: None)
    assert "n@e.st" not in seen[0].headers["User-Agent"]


class FakeClock:
    """Monotonic time that moves only when the client sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"


def budgeted_client(answers: list[httpx.Response], clock: FakeClock, budget: float) -> NewsClient:
    replies = iter(answers)
    return NewsClient(
        {"api.gdeltproject.org"},
        transport=httpx.MockTransport(lambda _: next(replies)),
        sleep=clock.sleep,
        clock=clock,
        time_budget=budget,
    )


def test_the_time_budget_stops_backoff_sleeps_that_would_pass_it() -> None:
    clock = FakeClock()
    client = budgeted_client([httpx.Response(429)] * 5, clock, budget=100)
    with pytest.raises(NewsRequestError, match=r"after 3 attempt\(s\); stopped: the run's time"):
        client.get(GDELT_DOC, {"query": "x"}, lambda: None)
    assert clock.sleeps == [15.0, 30.0]  # the third wait (60 s) would end at 105 s


def test_no_request_starts_once_the_budget_is_used() -> None:
    clock = FakeClock()
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=b"{}")

    client = NewsClient(
        {"api.gdeltproject.org"},
        transport=httpx.MockTransport(handler),
        clock=clock,
        time_budget=10,
    )
    assert client.get(GDELT_DOC, {"query": "x"}, lambda: None) is not None
    clock.now = 10.0
    with pytest.raises(NewsRequestError, match="not sent: stopped: the run's time budget"):
        client.get(GDELT_DOC, {"query": "y"}, lambda: None)
    assert len(sent) == 1


def test_the_news_budget_fits_inside_the_run_time_limit() -> None:
    """The last request may start just before the budget ends and wait for a GDELT token (one
    every 10 seconds) first; store() needs the rest."""
    gdelt_token_wait = 10.0
    assert FETCH_TIME_BUDGET_SECONDS + gdelt_token_wait + TIMEOUT_SECONDS < RUN_TIME_LIMIT_SECONDS


# ---------- schedules ----------


def test_interval_schedules() -> None:
    hourly, half_hourly = IntervalSchedule(60, 20), IntervalSchedule(30, 5)
    now = datetime(2026, 10, 6, 10, 20, tzinfo=UTC)
    assert hourly.next_after(now) == datetime(2026, 10, 6, 11, 20, tzinfo=UTC)  # strictly after
    assert half_hourly.next_after(now) == datetime(2026, 10, 6, 10, 35, tzinfo=UTC)
    slot = half_hourly.slot(now)
    assert (slot.start, slot.end) == (
        datetime(2026, 10, 6, 10, 5, tzinfo=UTC),
        datetime(2026, 10, 6, 10, 35, tzinfo=UTC),
    )


# ---------- GDELT runs under throttling ----------


def gdelt_job(
    answers: list[httpx.Response], clock: FakeClock | None = None, budget: float | None = None
) -> GdeltJob:
    replies = iter(answers)

    class Job(GdeltJob):
        def client(self) -> NewsClient:
            if clock is not None:
                return budgeted_client(list(replies), clock, budget or FETCH_TIME_BUDGET_SECONDS)
            return NewsClient(
                {"api.gdeltproject.org"},
                transport=httpx.MockTransport(lambda _: next(replies)),
                sleep=lambda _: None,
            )

    window = {"start": "20261001000000", "end": "20261002000000"}
    return Job({"tickers": ["AAPL", "MSFT", "NVDA"], **window}, Window())


def test_a_throttled_gdelt_run_keeps_what_it_got() -> None:
    ok = httpx.Response(200, content=b"{}")
    job = gdelt_job([ok] + [httpx.Response(429)] * 10)
    payloads = job.fetch(FetchContext(run_id=uuid4(), acquire=lambda: None))
    assert len(payloads) == 1  # AAPL kept; stopped at MSFT, NVDA not tried


def test_a_gdelt_run_that_gets_nothing_fails() -> None:
    job = gdelt_job([httpx.Response(429)] * 10)
    with pytest.raises(NewsRequestError, match="HTTP 429"):
        job.fetch(FetchContext(run_id=uuid4(), acquire=lambda: None))


def test_a_gdelt_run_out_of_time_keeps_what_it_got() -> None:
    clock = FakeClock()
    ok = httpx.Response(200, content=b"{}")
    job = gdelt_job([ok] + [httpx.Response(429)] * 10, clock, budget=40)
    payloads = job.fetch(FetchContext(run_id=uuid4(), acquire=lambda: None))
    assert len(payloads) == 1  # AAPL kept; MSFT stopped before a wait past 40 s, NVDA not tried
    assert clock.sleeps == [15.0]


def test_a_gdelt_run_out_of_time_with_nothing_fails() -> None:
    job = gdelt_job([httpx.Response(429)] * 10, FakeClock(), budget=40)
    with pytest.raises(NewsRequestError, match="time budget is used up"):
        job.fetch(FetchContext(run_id=uuid4(), acquire=lambda: None))
