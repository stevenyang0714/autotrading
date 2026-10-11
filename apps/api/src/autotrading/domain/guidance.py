"""Earnings guidance from 8-K exhibits (M1.5, ADR-026 E3, P1-3): explicit numeric outlooks for
revenue, EPS and margins, rule-based. Pure functions; only the sentence (at most 300
characters) is kept, never the document.

A statement needs a metric (revenue or sales and their growth, EPS, gross / operating / net
margin), a number or a range right after it, and either
- a forward word (expect, anticipate, outlook, guidance, forecast, project, target) and a future
  period (a quarter, a fiscal or full year) in the same sentence, or
- an outlook section: the lines after a heading that names an outlook or guidance and its
  period ("Fiscal Year 2026 Outlook", "NVIDIA's outlook for the third quarter of fiscal 2027 is
  as follows:"), whose bullets and table rows carry no verb.
Past results ("revenue was"), safe-harbor text, "(previously ...)" ranges and other metrics
(expenses, capital expenditures, tax rate) never count. "X, plus or minus Y%" and "plus or
minus N basis points" become a range. One statement per metric, range and period in a document.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from autotrading.domain.buyback_announcements import trim

GUIDANCE_VERSION = "0.1.0"
SECTION_LINES = 25  # an outlook section ends after this many lines, or at the next heading

Metric = Literal[
    "revenue", "revenue_growth", "eps", "gross_margin", "operating_margin", "net_margin"
]
GuidanceUnit = Literal["USD", "USD/shares", "percent"]
UNITS: dict[Metric, GuidanceUnit] = {
    "revenue": "USD",
    "revenue_growth": "percent",
    "eps": "USD/shares",
    "gross_margin": "percent",
    "operating_margin": "percent",
    "net_margin": "percent",
}
_OF_SALES = r"as\s+a\s+percent(?:age)?\s+of\s+(?:net\s+|total\s+)?(?:sales|revenues?)"
# Longest first: a margin or growth phrase wins over the plain word inside it.
_METRIC_PATTERNS: tuple[tuple[Metric, str], ...] = (
    ("gross_margin", rf"gross\s+(?:profit\s+)?margins?|gross\s+profit\s+{_OF_SALES}"),
    ("operating_margin", rf"operating\s+(?:income\s+)?margins?|operating\s+income\s+{_OF_SALES}"),
    ("net_margin", rf"net\s+(?:income\s+)?margins?|net\s+income\s+{_OF_SALES}"),
    ("eps", r"earnings\s+per\s+(?:diluted\s+)?share|\bEPS\b"),
    ("revenue_growth", r"comparable\s+(?:store\s+)?sales|(?:revenue|sales)\s+growth"),
    (
        "revenue",
        r"(?<!cost of )(?<!asset )\b(?:total\s+|net\s+)?(?:revenues?|sales)\b"
        r"(?!\s+and\s+(?:marketing|divestments))",
    ),
)
_METRICS = tuple((metric, re.compile(p, re.IGNORECASE)) for metric, p in _METRIC_PATTERNS)
_FORWARD = re.compile(
    r"\b(?:expects?|expected|expecting|anticipates?|anticipated|outlook|guidance|guides?|"
    r"forecasts?|projects?|projected|targets?)\b",
    re.IGNORECASE,
)
_ORDINAL = r"(?:first|second|third|fourth|1st|2nd|3rd|4th)"
_PERIOD = re.compile(
    rf"\b(?:(?:the\s+)?{_ORDINAL}[\s-]+quarter(?:\s+of)?(?:\s+fiscal(?:\s+year)?)?(?:\s+20\d\d)?"
    rf"|Q[1-4](?:\s?FY)?\s?'?(?:20)?\d\d|next\s+quarter"
    rf"|(?:full[\s-]+year|fiscal(?:\s+year)?|FY)\s?'?(?:20)?\d\d(?:\s+full[\s-]+year)?"
    rf"|20\d\d\s+full[\s-]+year|full[\s-]+year)\b",
    re.IGNORECASE,
)
_HEADING = re.compile(r"\b(?:outlook|guidance)\b", re.IGNORECASE)
_SECTION_END = re.compile(
    r"^(?:\w+\s+)?(?:highlights|results|summary|conference\s+call|about\s|safe\s+harbor|"
    r"forward[\s-]+looking|non-gaap|use\s+of\s+non)",
    re.IGNORECASE,
)
_SAFE_HARBOR = re.compile(
    r"forward[\s-]+looking\s+statements|safe\s+harbor|risks\s+and\s+uncertainties|"
    r"actual\s+results",
    re.IGNORECASE,
)
_PAST = re.compile(
    r"\b(?:was|were|increased|decreased|grew|rose|fell|declined|reported|benefit|earned|"
    r"generated|achieved|delivered|preliminary|versus|compared|relative\s+to|shortfall)\b"
    r"|\b(?:up|down)\s+\d|\bvs\.",
    re.IGNORECASE,
)
HEADING_CHARS = 140  # an outlook heading is a short line
_PREVIOUSLY = re.compile(r"\((?:previously|prior)[^)]*\)", re.IGNORECASE)
_ADJUSTED = re.compile(r"\b(?:adjusted|non-?GAAP|excluding)", re.IGNORECASE)  # "Adjusted1"
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])|\s*•\s*")

_NUM = r"\d[\d,]*(?:\.\d+)?"
_SCALE = r"(?:billion|million)"
_TO = r"\s*(?:-|\u2013|\u2014|to|and)\s*"  # hyphen, en dash, em dash
_USD = re.compile(
    rf"\$\s?(?P<low>{_NUM})\s?(?P<low_scale>{_SCALE})?(?:{_TO}\$?\s?(?P<high>{_NUM}))?"
    rf"\s?(?P<high_scale>{_SCALE})",
    re.IGNORECASE,
)
_PER_SHARE = re.compile(
    rf"\$\s?(?P<low>\d+\.\d+)(?:{_TO}\$?\s?(?P<high>\d+\.\d+))?(?!\d|\s?(?:billion|million))",
    re.IGNORECASE,
)
_PERCENT = re.compile(
    rf"(?P<low>-?\d+(?:\.\d+)?)\s?(?:%|percent)?(?:{_TO}(?P<high>-?\d+(?:\.\d+)?))?\s?(?:%|percent)",
    re.IGNORECASE,
)
_PLUS_MINUS = re.compile(
    r"plus\s+or\s+minus\s+(?P<pm>\d+(?:\.\d+)?)\s?(?P<unit>%|percent|basis\s+points)",
    re.IGNORECASE,
)
_BY = re.compile(r"\bby\b", re.IGNORECASE)
_AFTER_VALUE = re.compile(r"^[\s,;]*(?:respectively[\s,;]*)?", re.IGNORECASE)
_SCALES = {"billion": Decimal(10**9), "million": Decimal(10**6)}
_REACH = 160  # characters after a metric in which its value must start


@dataclass(frozen=True)
class Guidance:
    metric: Metric
    low: Decimal
    high: Decimal  # equal to low for a point
    unit: GuidanceUnit
    period: str  # as written: "third quarter of fiscal 2027", "Fiscal Year 2026"
    adjusted: bool  # adjusted / non-GAAP
    sentence: str  # at most MAX_SENTENCE characters
    rule: Literal["sentence", "outlook_section"]


def _number(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


@dataclass(frozen=True)
class _Value:
    low: Decimal
    high: Decimal
    start: int
    end: int
    pair: bool  # "X and Y": two values (GAAP and non-GAAP, "respectively"), not a range


def _value(metric: Metric, text: str) -> _Value | None:
    """The first value in `text` in the metric's unit, if any."""
    unit = UNITS[metric]
    if unit == "USD":
        found = _USD.search(text)
        if found is None:
            return None
        high_scale = _SCALES[found.group("high_scale").lower()]
        low_scale = _SCALES[found.group("low_scale").lower()] if found.group("low_scale") else None
        low = _number(found.group("low")) * (low_scale or high_scale)
        high = _number(found.group("high")) * high_scale if found.group("high") else low
        low, high = low.quantize(Decimal(1)), high.quantize(Decimal(1))
    else:
        found = (_PER_SHARE if unit == "USD/shares" else _PERCENT).search(text)
        if found is None:
            return None
        low = _number(found.group("low"))
        high = _number(found.group("high")) if found.group("high") else low
    joined = text[found.start("low") : found.start("high")] if found.group("high") else ""
    return _Value(low, high, found.start(), found.end(), bool(re.search(r"\band\b", joined)))


def _plus_minus(metric: Metric, low: Decimal, high: Decimal, rest: str) -> tuple[Decimal, Decimal]:
    """A point followed by "plus or minus" becomes a range."""
    found = _PLUS_MINUS.match(rest)
    if found is None or low != high:
        return low, high
    spread = _number(found.group("pm"))
    if found.group("unit").lower().startswith("basis"):
        delta = spread / 100  # basis points of a percent value
    elif UNITS[metric] == "percent":
        delta = spread  # percentage points
    else:
        delta = low * spread / 100  # a share of the amount
        delta = delta.quantize(Decimal(1) if UNITS[metric] == "USD" else Decimal("0.0001"))
    return low - delta, high + delta


def _metrics(sentence: str) -> list[tuple[Metric, int, int]]:
    """(metric, start, end) of each metric phrase, in order, without overlaps."""
    found = sorted(
        ((metric, m.start(), m.end()) for metric, p in _METRICS for m in p.finditer(sentence)),
        key=lambda f: (f[1], -(f[2] - f[1])),
    )
    out: list[tuple[Metric, int, int]] = []
    for item in found:
        if not out or item[1] >= out[-1][2]:
            out.append(item)
    return out


def _statements(
    sentence: str, period: str, rule: Literal["sentence", "outlook_section"]
) -> list[Guidance]:
    text = _PREVIOUSLY.sub("", sentence)
    phrases = _metrics(text)
    adjusted = bool(_ADJUSTED.search(text)) and not re.search(
        r"\bGAAP\s+and\s+non-?GAAP\b", text, re.IGNORECASE
    )
    out = []
    for i, (metric, _, end) in enumerate(phrases):
        stop = min(end + _REACH, phrases[i + 1][1] if i + 1 < len(phrases) else len(text))
        window = text[end:stop]
        found = _value(metric, window)
        if found is None or _BY.search(window[: found.start]):
            continue  # no value, or a change ("increase sales by $1 billion"), not a level
        if rule == "sentence" and _FORWARD.search(text[: end + found.end]) is None:
            continue  # the forward word only follows the value: a result, then an outlook
        # After the value: ", respectively," and "plus or minus N" belong to it.
        rest = _AFTER_VALUE.sub("", window[found.end :])
        spread = _PLUS_MINUS.match(rest)
        tail = rest[spread.end() :] if spread else rest
        if rule == "outlook_section" and _value(metric, tail.split(".")[0]) is not None:
            continue  # a second value: a table comparing an outlook with results
        if found.pair and "respectively" in window.lower():
            # "GAAP and non-GAAP ... X% and Y%, respectively": two points, not a range.
            points = [(found.low, found.low, False), (found.high, found.high, True)]
        else:
            points = [(found.low, found.high, adjusted)]
        for low, high, is_adjusted in points:
            low, high = _plus_minus(metric, low, high, rest)
            out.append(
                Guidance(
                    metric=metric,
                    low=low,
                    high=high,
                    unit=UNITS[metric],
                    period=period,
                    adjusted=is_adjusted,
                    sentence=trim(sentence, end),
                    rule=rule,
                )
            )
    return out


def guidance(text: str) -> list[Guidance]:
    """Statements of a document's text (domain/buyback_announcements.document_text with
    rows=True: one line per block or table row)."""
    found: list[Guidance] = []
    section: str | None = None
    left = 0
    for line in (line for line in text.split("\n") if line.strip()):
        if section is not None:
            left -= 1
            if left <= 0 or _SECTION_END.match(line) or _SAFE_HARBOR.search(line):
                section = None
        period = _PERIOD.search(line)
        if (
            period
            and _HEADING.search(line)
            and len(line) <= HEADING_CHARS
            and not _PAST.search(line)
            and not _SAFE_HARBOR.search(line)
        ):
            section, left = period.group(0), SECTION_LINES
        for sentence in (s.strip() for s in _SPLIT.split(line) if s and s.strip()):
            if _SAFE_HARBOR.search(sentence) or _PAST.search(sentence):
                continue
            own_period = _PERIOD.search(sentence)
            if _FORWARD.search(sentence) and own_period:
                found += _statements(sentence, own_period.group(0), "sentence")
            elif section is not None:
                found += _statements(
                    sentence, own_period.group(0) if own_period else section, "outlook_section"
                )
    return _unique(found)


def _unique(found: list[Guidance]) -> list[Guidance]:
    """One statement per metric, basis and midpoint; a range wins over the same point."""
    kept: dict[tuple[str, bool, Decimal], Guidance] = {}
    for g in found:
        key = (g.metric, g.adjusted, (g.low + g.high) / 2)
        if key not in kept or (kept[key].low == kept[key].high and g.low != g.high):
            kept[key] = g
    return list(kept.values())
