"""News (M0.8, ADR-018): URL and title normalisation, duplicate grouping, summaries, publisher
tiers and rule-based company mentions. Pure; fetching and storage live in adapters/news and
repositories/news.

- Duplicates: the same canonical URL is the same article. Copies of one story (syndication,
  reposts) on different sites share a duplicate group: same normalised title, or titles whose
  word sets overlap by at least TITLE_SIMILARITY, published within GROUP_WINDOW of each other.
  Two articles from one site are grouped only by URL or an identical normalised title: a
  site's own series of long, similar titles (one White House order per product) are separate
  releases, while a site posting the same headline again is a repost. A new article joins the
  most similar group; a group never changes once assigned (append-only storage).
- Mentions: company names and aliases (case-sensitive, whole words), exchange-qualified tickers
  ($AAPL, NASDAQ: AAPL) and bare upper-case tickers that are not ordinary words. Titles only.
"""

import html
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

NewsKind = Literal["article", "press_release", "official"]
TimeBasis = Literal["publisher", "first_seen"]
MentionRule = Literal["exchange_ticker", "feed_issuer", "company_name", "bare_ticker"]

SNIPPET_MAX_CHARS = 300
TITLE_SIMILARITY = 0.85
MIN_TITLE_WORDS = 4
GROUP_WINDOW = timedelta(hours=72)
EXTRACTOR_VERSION = "0.1.0"

# Confidence per rule: deterministic matches 1.0; name and bare-ticker matches are rule weights,
# not yet measured against labelled data (ADR-018).
RULE_CONFIDENCE: dict[MentionRule, Decimal] = {
    "exchange_ticker": Decimal("1.0"),
    "feed_issuer": Decimal("1.0"),
    "company_name": Decimal("0.8"),
    "bare_ticker": Decimal("0.7"),
}

TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "ocid", "cmpid", "smid", "ref", "taid", "mod"}
)
HOST_PREFIXES = ("www.", "m.", "amp.", "mobile.")


# ---------- URLs ----------


def canonical_url(url: str) -> str:
    """One spelling per article: https, no www/m/amp host prefix, no default port, no
    tracking parameters, no fragment, no trailing slash or /amp suffix."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    for prefix in HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix) :]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/amp/?$", "", parts.path) or "/"
    path = path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
        )
    )
    return urlunsplit(("https", netloc, path, query, ""))


def publisher_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for prefix in HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def _domain_and_parents(domain: str) -> list[str]:
    labels = domain.lower().split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


@dataclass(frozen=True)
class PublisherTiers:
    """config/news_publishers.yaml: tier per domain, official suffixes, default, blocked."""

    publishers: Mapping[str, tuple[int, str]]  # domain -> (tier, display name)
    official_suffixes: tuple[str, ...]
    default_tier: int
    blocked: frozenset[str] = frozenset()

    def is_blocked(self, domain: str) -> bool:
        return any(candidate in self.blocked for candidate in _domain_and_parents(domain))

    def lookup(self, domain: str) -> tuple[int, str | None]:
        """(tier, known publisher name) for a domain or any of its parent domains."""
        for candidate in _domain_and_parents(domain):
            if candidate in self.publishers:
                return self.publishers[candidate]
        if domain.endswith(self.official_suffixes):
            return 1, None
        return self.default_tier, None


# ---------- titles and summaries ----------


def plain_text(value: str) -> str:
    """HTML tags and entities removed, whitespace collapsed."""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


# WordPress feeds end every summary with "The post <title> appeared first on <site>."
_WORDPRESS_FOOTER = re.compile(r"\s*The post .{1,300}? appeared first on .{1,120}?\.?\s*$")


def snippet(value: str | None) -> str | None:
    """A short plain-text summary: at most SNIPPET_MAX_CHARS characters, cut at a word."""
    if not value:
        return None
    text = _WORDPRESS_FOOTER.sub("", plain_text(value))
    if not text:
        return None
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[: SNIPPET_MAX_CHARS - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > SNIPPET_MAX_CHARS // 2 else cut).rstrip(" ,;:-") + "…"


_SUFFIX_SEPARATORS = re.compile("\\s+(?:\\||-|\u2013|\u2014|::)\\s+")
RIGHT_QUOTE = "\u2019"  # typographic apostrophe, common in headlines (Lowe\u2019s)


def normalize_title(title: str) -> str:
    """Lower-case words of a title without a trailing publisher name (" | The Arkansas
    Democrat", " - Reuters"); punctuation, accents and spacing removed."""
    text = plain_text(title)
    parts = _SUFFIX_SEPARATORS.split(text)
    if len(parts) > 1 and len(parts[-1].split()) <= 6 and len(" ".join(parts[:-1]).split()) >= 3:
        text = " ".join(parts[:-1])
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("'", "").replace(RIGHT_QUOTE, "")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def title_similarity(a: str, b: str) -> float:
    """Word-set overlap (Jaccard) of two normalised titles."""
    words_a, words_b = set(a.split()), set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


# ---------- duplicate groups ----------


@dataclass(frozen=True)
class GroupCandidate:
    item_id: UUID
    group_id: UUID
    canonical_url: str
    title_key: str
    published_at: datetime
    publisher_domain: str


def duplicate_group(
    *,
    canonical: str,
    title_key: str,
    published_at: datetime,
    domain: str,
    existing: Iterable[GroupCandidate],
) -> UUID | None:
    """The group a new article joins, or None to start its own. Same URL wins; otherwise the
    most similar title within GROUP_WINDOW, at least TITLE_SIMILARITY (from the same site only
    an identical title); ties go to the earliest article."""
    best: tuple[float, datetime, UUID] | None = None
    long_enough = len(title_key.split()) >= MIN_TITLE_WORDS
    for other in existing:
        if other.canonical_url == canonical:
            return other.group_id
        if not long_enough or abs(other.published_at - published_at) > GROUP_WINDOW:
            continue
        if other.title_key == title_key:
            score = 1.0
        elif other.publisher_domain == domain:
            continue  # one site's similar titles are separate releases
        else:
            score = title_similarity(title_key, other.title_key)
        if score < TITLE_SIMILARITY:
            continue
        if best is None or score > best[0] or (score == best[0] and other.published_at < best[1]):
            best = (score, other.published_at, other.group_id)
    return best[2] if best else None


# ---------- company mentions ----------


@dataclass(frozen=True)
class Company:
    ticker: str
    names: tuple[str, ...]  # SEC name without suffixes, plus configured aliases
    bare_ticker_allowed: bool


@dataclass(frozen=True)
class Mention:
    ticker: str
    rule: MentionRule
    matched_text: str

    @property
    def confidence(self) -> Decimal:
        return RULE_CONFIDENCE[self.rule]


_LEGAL_SUFFIX = re.compile(
    r"(?:,?\s+(?:&\s*co|inc|incorporated|corp|corporation|co|company|companies|ltd|plc|"
    r"holdings?|platforms|group|n\.?a)\.?)+$",
    re.IGNORECASE,
)


def short_company_name(sec_name: str) -> str:
    """SEC conformed name without legal suffixes and a trailing /DE/-style state tag:
    "Apple Inc." -> "Apple", "LOWES COMPANIES INC" -> "LOWES"."""
    name = re.sub(r"\s*/[A-Z]{2}/?\s*$", "", sec_name.strip())
    return _LEGAL_SUFFIX.sub("", name).strip(" ,.")


def _word_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w$]){re.escape(name)}(?:'s)?(?![\w-])")


def company_names(sec_name: str | None, aliases: Iterable[str]) -> tuple[str, ...]:
    """Names matched in titles: the configured aliases, plus the SEC name without suffixes when
    it is written in mixed case (all-caps conformed names like "NVIDIA CORP" never match a
    headline case-sensitively, so their aliases carry them)."""
    names = list(aliases)
    if sec_name:
        short = short_company_name(sec_name)
        if short and short != short.upper() and short not in names:
            names.append(short)
    # Longest first, so "Meta Platforms" is reported rather than "Meta".
    return tuple(sorted(names, key=len, reverse=True))


def find_mentions(title: str, companies: Sequence[Company]) -> list[Mention]:
    """Universe companies named in a title, at most one mention per company (strongest rule)."""
    text = plain_text(title).replace(RIGHT_QUOTE, "'")
    found: dict[str, Mention] = {}
    order: list[MentionRule] = ["exchange_ticker", "company_name", "bare_ticker"]
    for company in companies:
        symbol = re.escape(company.ticker)
        exchange = re.search(rf"(?:\$|\b(?:NASDAQ|NYSE|Nasdaq|Nyse)\s*:\s*){symbol}\b", text)
        if exchange:
            found[company.ticker] = Mention(company.ticker, "exchange_ticker", exchange.group(0))
            continue
        for name in company.names:
            match = _word_pattern(name).search(text)
            if match:
                found[company.ticker] = Mention(company.ticker, "company_name", match.group(0))
                break
        if company.ticker not in found and company.bare_ticker_allowed:
            bare = re.search(rf"(?<![\w$]){symbol}(?![\w-])", text)
            if bare:
                found[company.ticker] = Mention(company.ticker, "bare_ticker", bare.group(0))
    return sorted(found.values(), key=lambda m: (order.index(m.rule), m.ticker))
