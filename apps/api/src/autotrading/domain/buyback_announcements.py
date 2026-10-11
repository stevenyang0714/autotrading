"""Buyback announcements (M1.4a, ADR-025 B1): repurchase authorizations, plans and remaining
amounts, read from the sentences of 8-K documents and issuer press releases. Pure functions;
rule-based, no model.

A sentence counts only when its dollar amount is tied to one of:
- an authorization: "authorized / approved [an additional] $X ... repurchase" -> `new`, or
  `increase` when the words between the verb and the amount say additional, increase, expand,
  raise or further; "announced an increase of $X", "$X increase in our repurchase
  authorization" and "$X ... repurchase authorization increase" -> `increase`;
- a plan: "plan(s) to repurchase / buy back / deliver [up to] $X" -> `plan` (B9 counts it);
- a remaining amount: "$X remaining under ... repurchase", or "remaining ... to $X" -> `remaining`
  (also kept beside an authorization in the same sentence).
Amounts of repurchases already made ("returned $X ... through share repurchases") never match,
because no authorization, plan or remaining wording governs them. Recaps are not
announcements: "previously authorized / announced", "since inception", cumulative totals, and
status lines ("the Firm is / was authorized to purchase up to $X", "had authorized") and the
footnotes of financial supplements ("(a) The Firm's Board authorized ...") never give a new or
increased authorization. A stated date ("On August 26,
2025, the Board approved ...") is kept, so a later filing repeating it is the same event.

Only the matched sentence is kept, at most 300 characters around the amount, and the link;
never the document (copyright and storage, as M1.5's exhibit rule).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from typing import Literal

EXTRACTOR_VERSION = "0.1.3"
MAX_SENTENCE = 300

Kind = Literal["new", "increase", "plan", "remaining"]

_UNITS = {"billion": Decimal(10**9), "million": Decimal(10**6)}
AMOUNT = r"\$\s?(?P<{name}>\d[\d,]*(?:\.\d+)?)\s?(?P<{name}_unit>billion|million)\b"
_REPURCHASE = re.compile(r"repurchase|buy-?\s?back|share\s+buy|stock\s+buy", re.IGNORECASE)
_AUTHORIZED = re.compile(
    r"\b(?:authori[sz](?:ed|es|ing)|approv(?:ed|es|ing))\b(?P<between>[^.$]{0,120}?)"
    + AMOUNT.format(name="amount"),
    re.IGNORECASE,
)
_HEADLINE_NEW = re.compile(
    r"\bannounc\w*\s+(?:an?\s+)?(?:new\s+)?"
    + AMOUNT.format(name="amount")
    + r"\s+(?:share\s+|stock\s+)?(?:repurchase|buyback)\s+(?:authori[sz]ation|program)\b",
    re.IGNORECASE,
)
_RECAP = re.compile(
    r"\bpreviously\s+(?:authori[sz]ed|announced|approved)\b|\bsince\s+(?:the\s+)?inception\b"
    r"|\bcumulative(?:ly)?\b|\bincluding\s+the\s+above\b"
    r"|\b(?:is|are|was|were|remains?)\s+authori[sz]ed\s+to\b|\bhad\s+(?:authori[sz]ed|approved)\b"
    r"|^\W*\([a-z0-9]\)",  # a footnote of a financial supplement restates the program
    re.IGNORECASE,
)
_EXECUTED = re.compile(r"\b(?:repurchased|bought|returned|spent|purchased|paid)\b", re.IGNORECASE)
_ANNOUNCED_INCREASE = re.compile(
    r"\bannounc\w*\s+(?:an?\s+)?(?:increase|addition)\w*\s+(?:of\s+)?"
    + AMOUNT.format(name="amount"),
    re.IGNORECASE,
)
_AMOUNT_INCREASE = re.compile(
    AMOUNT.format(name="amount")
    + r"\s+(?:increase|addition)\s+(?:in|to)\s+(?:\w+\s+){0,3}(?:repurchase|buyback)",
    re.IGNORECASE,
)
_HEADLINE_INCREASE = re.compile(
    AMOUNT.format(name="amount")
    + r"\s+(?:share\s+|stock\s+)?(?:repurchase|buyback)\s+(?:authori[sz]ation|program)\s+increase",
    re.IGNORECASE,
)
_PLAN = re.compile(
    r"\bplan\w*\s+to\s+(?:repurchase|buy\s?back|deliver|purchase)\s+"
    r"(?:up\s+to\s+|about\s+|approximately\s+|roughly\s+)?" + AMOUNT.format(name="amount"),
    re.IGNORECASE,
)
_REMAINING_AFTER = re.compile(
    AMOUNT.format(name="remaining")
    + r"\s+(?:remain\w*|left|available)(?:\s+(?:available|and|authori[sz]ed))*"
    r"\s+(?:under|in|on|for)\b[^.]{0,80}?(?:repurchase|buyback)",
    re.IGNORECASE,
)
_REMAINING_TO = re.compile(
    r"\bremaining\b[^.$]{0,60}?\bto\s+" + AMOUNT.format(name="remaining"), re.IGNORECASE
)
_INCREASE_WORDS = re.compile(
    r"\b(?:additional|incremental|increas\w*|expan\w*|rais\w*|further)\b", re.IGNORECASE
)
_STATED_DATE = re.compile(
    r"^\W*on\s+(?P<month>january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
_VOID_TAGS = frozenset({"br", "img", "hr", "meta", "input", "link", "col", "area", "base", "wbr"})
_DEBT = re.compile(r"\b(?:notes|debentures|bonds|tender\s+offer|debt)\b", re.IGNORECASE)
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "tr", "td", "th", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])|\s*•\s*")


@dataclass(frozen=True)
class Statement:
    kind: Kind
    amount: Decimal  # USD: authorized, increased, planned, or remaining for kind `remaining`
    remaining_amount: Decimal | None  # a remaining amount the same sentence states
    stated_date: date | None  # "On <Month> <day>, <year>, ..." at the start of the sentence
    sentence: str  # at most MAX_SENTENCE characters around the amount
    rule: str  # the pattern that matched


_CELL_TAGS = frozenset({"td", "th"})


class _Text(HTMLParser):
    def __init__(self, rows: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0
        # rows: a table row is one line, its cells separated by " | " (M1.5 guidance tables)
        self._rows = rows
        self._in_row = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        style = dict(attrs).get("style") or ""
        if tag not in _VOID_TAGS and (
            self._hidden
            or tag in ("script", "style", "ix:header")
            or "display:none" in style.replace(" ", "")
        ):
            self._hidden += 1  # hidden, or nested inside hidden content
        self.parts.append(self._break(tag))
        if self._rows and tag == "tr":
            self._in_row += 1

    def handle_endtag(self, tag: str) -> None:
        if self._hidden and tag not in _VOID_TAGS:
            self._hidden -= 1
        if self._rows and tag == "tr":
            self._in_row = max(0, self._in_row - 1)
        self.parts.append(self._break(tag))

    def _break(self, tag: str) -> str:
        """What a tag adds: a line break for blocks; in rows mode, cells inside a row are
        separated by " | " and blocks nested in them by a space."""
        if self._rows and self._in_row and tag != "tr":
            if tag in _CELL_TAGS:
                return " | "
            return " " if tag in _BLOCK_TAGS else ""
        return "\n" if tag in _BLOCK_TAGS else ""

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def document_text(raw: bytes, rows: bool = False) -> str:
    """Visible text of an HTML document, one line per block element; with `rows`, one line per
    table row, its non-empty cells separated by " | "."""
    parser = _Text(rows)
    parser.feed(raw.decode("utf-8", errors="replace"))
    text = "".join(parser.parts).replace("\xa0", " ").replace("​", "")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    if rows:
        lines = (" | ".join(c.strip() for c in line.split("|") if c.strip()) for line in lines)
    return "\n".join(lines)


def sentences(text: str) -> list[str]:
    """Sentences per block (line); bullets split too."""
    out: list[str] = []
    for block in text.split("\n"):
        out += [s.strip() for s in _SPLIT.split(block) if s and s.strip()]
    return out


def _amount(match: re.Match[str], name: str) -> Decimal:
    number = Decimal(match.group(name).replace(",", ""))
    return (number * _UNITS[match.group(f"{name}_unit").lower()]).quantize(Decimal(1))


def trim(sentence: str, at: int) -> str:
    """At most MAX_SENTENCE characters, centred on position `at` when cut."""
    if len(sentence) <= MAX_SENTENCE:
        return sentence
    start = max(0, min(at - MAX_SENTENCE // 2, len(sentence) - MAX_SENTENCE + 2))
    end = start + MAX_SENTENCE - 2
    cut = sentence[start:end].strip()
    return ("…" if start > 0 else "") + cut + ("…" if end < len(sentence) else "")


def _stated_date(sentence: str) -> date | None:
    found = _STATED_DATE.match(sentence)
    if found is None:
        return None
    try:
        return date(
            int(found.group("year")), _MONTHS[found.group("month").lower()], int(found.group("day"))
        )
    except ValueError:
        return None


def statement(sentence: str) -> Statement | None:
    """The authorization, plan or remaining amount a sentence states, if any (never debt:
    notes, bonds or tender offers)."""
    if not _REPURCHASE.search(sentence) or _DEBT.search(sentence):
        return None
    remaining_match = _REMAINING_AFTER.search(sentence) or _REMAINING_TO.search(sentence)
    remaining = _amount(remaining_match, "remaining") if remaining_match else None
    kind: Kind
    if (headline := _HEADLINE_INCREASE.search(sentence)) is not None:
        found, kind, rule = headline, "increase", "headline_increase"
    elif (
        increase := _ANNOUNCED_INCREASE.search(sentence) or _AMOUNT_INCREASE.search(sentence)
    ) is not None and not _RECAP.search(sentence):
        found, kind, rule = increase, "increase", "announced_increase"
    elif (
        (new := _HEADLINE_NEW.search(sentence)) is not None
        and not _INCREASE_WORDS.search(sentence[new.end() : new.end() + 12])
        and not _RECAP.search(sentence)
    ):
        found, kind, rule = new, "new", "headline_new"
    elif (
        (authorized := _AUTHORIZED.search(sentence)) is not None
        and not _EXECUTED.search(authorized.group("between"))
        and not _RECAP.search(sentence)
    ):
        found, rule = authorized, "authorized"
        kind = "increase" if _INCREASE_WORDS.search(authorized.group("between")) else "new"
        if remaining_match is not None and remaining_match.start() <= authorized.start("amount"):
            # "$X remaining under the authorization approved ..." is a remaining amount.
            found, kind, rule = remaining_match, "remaining", "remaining"
    elif (plan := _PLAN.search(sentence)) is not None:
        found, kind, rule = plan, "plan", "plan"
    elif remaining_match is not None:
        found, kind, rule = remaining_match, "remaining", "remaining"
    else:
        return None
    name = "remaining" if kind == "remaining" else "amount"
    amount = _amount(found, name)
    return Statement(
        kind=kind,
        amount=amount,
        remaining_amount=remaining if kind != "remaining" else None,
        stated_date=_stated_date(sentence),
        sentence=trim(sentence, found.start(name)),
        rule=rule,
    )


def statements(text: str) -> list[Statement]:
    """Every statement of a document's text, once per kind, amount and stated date (a summary
    may list several programs of the same size, each with its own date)."""
    seen: set[tuple[Kind, Decimal, date | None]] = set()
    out: list[Statement] = []
    for sentence in sentences(text):
        found = statement(sentence)
        if found is not None and (key := (found.kind, found.amount, found.stated_date)) not in seen:
            seen.add(key)
            out.append(found)
    return out
