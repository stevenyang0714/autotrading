"""A filing's own XBRL instance (M1.1, ADR-021): the `{primary document}_htm.xml` SEC extracts
from every inline XBRL filing, under www.sec.gov/Archives.

Two uses, both pure functions here (no I/O):
- reconciliation: the filing's non-dimensional values, shaped like company facts so the same
  concept selection applies (`as_companyfacts` -> parsing.select_values);
- class sums: companies with several share classes tag share counts per class only (Meta's
  Class A and B, Alphabet's cover page). When a filing reports no total, the common classes are
  added (`class_sums`) if they are standard us-gaap common class members, or if the same filing
  confirms the set: on some date its classes add up exactly to a total it reports.
"""

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from autotrading.adapters.sec.parsing import SEC_ARCHIVES, XbrlValue

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
# us-gaap/2025, dei/2025; before 2020 dated: us-gaap/2019-01-31, dei/2019-01-31.
TAXONOMY_URI = re.compile(
    r"^http://(?:fasb\.org/(us-gaap|srt)|xbrl\.sec\.gov/(dei))/\d{4}(?:-\d{2}-\d{2})?$"
)

CLASS_AXIS = "us-gaap:StatementClassOfStockAxis"
EQUITY_AXIS = "us-gaap:StatementEquityComponentsAxis"
COMMON_STOCK = "us-gaap:CommonStockMember"
STANDARD_COMMON_CLASS = re.compile(r"^us-gaap:Common(?:Class[A-Z]|Stock)Member$")
BALANCE_SHARES = "us-gaap:CommonStockSharesOutstanding"
SHARE_COUNTS = {
    BALANCE_SHARES: "shares_outstanding",
    "dei:EntityCommonStockSharesOutstanding": "shares_outstanding_cover",
}
SUM_OF_CLASSES = " (sum of classes)"
# Read for balance identities in reconciliation, not stored as metrics.
IDENTITY_CONCEPTS = frozenset({"us-gaap:Assets", "us-gaap:LiabilitiesAndStockholdersEquity"})


def instance_url(cik: str, accession: str, primary_document: str) -> str:
    stem = primary_document.rsplit(".", 1)[0]
    return f"{SEC_ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{stem}_htm.xml"


@dataclass(frozen=True)
class Context:
    start: date | None  # None for instants
    end: date
    dims: tuple[tuple[str, str], ...]  # (axis, member), sorted; typed members as (axis, "")


@dataclass(frozen=True)
class InstanceFact:
    concept: str  # qualified: us-gaap:X, dei:X, srt:X
    context: Context
    unit: str  # USD, shares, USD/shares, pure, ...
    value: Decimal
    decimals: int | None  # None: INF (exact)


def _unit_name(unit: ET.Element) -> str:
    def measure(element: ET.Element | None) -> str:
        text = (element.findtext(f"{XBRLI}measure") if element is not None else None) or ""
        return text.strip().split(":")[-1]

    divide = unit.find(f"{XBRLI}divide")
    if divide is not None:
        numerator = measure(divide.find(f"{XBRLI}unitNumerator"))
        denominator = measure(divide.find(f"{XBRLI}unitDenominator"))
        return f"{numerator}/{denominator}"
    return measure(unit)


def _context(element: ET.Element) -> Context:
    period = element.find(f"{XBRLI}period")
    if period is None:
        raise ValueError(f"context {element.get('id')} has no period")
    instant = period.findtext(f"{XBRLI}instant")
    dims = sorted(
        [
            (m.get("dimension", ""), (m.text or "").strip())
            for m in element.iter(f"{XBRLDI}explicitMember")
        ]
        + [(m.get("dimension", ""), "") for m in element.iter(f"{XBRLDI}typedMember")]
    )
    if instant:
        return Context(None, date.fromisoformat(instant.strip()), tuple(dims))
    start, end = period.findtext(f"{XBRLI}startDate"), period.findtext(f"{XBRLI}endDate")
    if not start or not end:
        raise ValueError(f"context {element.get('id')} has an incomplete period")
    return Context(date.fromisoformat(start.strip()), date.fromisoformat(end.strip()), tuple(dims))


def _decimals(value: str | None) -> int | None:
    if value is None or value.strip().upper() == "INF":
        return None
    return int(value)


def parse_instance(content: bytes) -> list[InstanceFact]:
    """Numeric facts of the us-gaap, dei and srt taxonomies. Where one concept, context and unit
    is tagged more than once, the most precise value is kept (equal precision: all kept)."""
    root = ET.fromstring(content)
    contexts = {e.get("id", ""): _context(e) for e in root.findall(f"{XBRLI}context")}
    units = {e.get("id", ""): _unit_name(e) for e in root.findall(f"{XBRLI}unit")}
    grouped: dict[tuple[str, str, str], list[InstanceFact]] = defaultdict(list)
    for element in root:
        unit_ref, context_ref = element.get("unitRef"), element.get("contextRef")
        if unit_ref is None or context_ref is None or element.get(XSI_NIL) == "true":
            continue
        namespace, _, name = element.tag[1:].partition("}")
        match = TAXONOMY_URI.match(namespace)
        if match is None:
            continue
        try:
            value = Decimal((element.text or "").strip())
        except InvalidOperation:
            continue
        fact = InstanceFact(
            concept=f"{match.group(1) or match.group(2)}:{name}",
            context=contexts[context_ref],
            unit=units[unit_ref],
            value=value,
            decimals=_decimals(element.get("decimals")),
        )
        grouped[(fact.concept, context_ref, fact.unit)].append(fact)
    facts: list[InstanceFact] = []
    for group in grouped.values():
        best = max(_precision(f) for f in group)
        kept = {f.value: f for f in group if _precision(f) == best}
        facts.extend(kept.values())
    return facts


def _precision(fact: InstanceFact) -> float:
    return float("inf") if fact.decimals is None else fact.decimals


def as_companyfacts(
    facts: list[InstanceFact], accession: str, form: str, filed: date
) -> dict[str, Any]:
    """The filing's non-dimensional values in the company facts layout (`select_values`)."""
    shaped: dict[str, dict[str, Any]] = defaultdict(dict)
    for fact in facts:
        if fact.context.dims:
            continue
        taxonomy, name = fact.concept.split(":", 1)
        observation: dict[str, Any] = {
            "accn": accession,
            "val": fact.value,
            "end": fact.context.end.isoformat(),
            "filed": filed.isoformat(),
            "form": form,
        }
        if fact.context.start is not None:
            observation["start"] = fact.context.start.isoformat()
        concept = shaped[taxonomy].setdefault(name, {"units": {}})
        concept["units"].setdefault(fact.unit, []).append(observation)
    return {"facts": dict(shaped)}


@dataclass(frozen=True)
class ClassSumResult:
    values: list[XbrlValue]
    findings: list[str]  # class sets that could not be confirmed, not added


def class_sums(facts: list[InstanceFact], accession: str, form: str, filed: date) -> ClassSumResult:
    totals: dict[tuple[str, date], Decimal] = {}
    confirmed_totals: dict[date, Decimal] = {}  # common stock totals, by balance-sheet date
    by_class: dict[tuple[str, date], dict[str, Decimal]] = defaultdict(dict)
    for fact in facts:
        if fact.concept not in SHARE_COUNTS or fact.unit != "shares":
            continue
        key = (fact.concept, fact.context.end)
        dims = fact.context.dims
        if not dims:
            totals[key] = fact.value
            if fact.concept == BALANCE_SHARES:
                confirmed_totals[fact.context.end] = fact.value
        elif dims == ((EQUITY_AXIS, COMMON_STOCK),) and fact.concept == BALANCE_SHARES:
            confirmed_totals.setdefault(fact.context.end, fact.value)
        elif len(dims) == 1 and dims[0][0] == CLASS_AXIS:
            by_class[key][dims[0][1]] = fact.value

    confirmed_sets = {
        frozenset(classes)
        for (concept, end), classes in by_class.items()
        if concept == BALANCE_SHARES
        and end in confirmed_totals
        and sum(classes.values()) == confirmed_totals[end]
    }
    values, findings = [], []
    for (concept, end), classes in sorted(by_class.items()):
        if (concept, end) in totals:
            continue  # the filing reports a total: nothing to add
        members = frozenset(classes)
        if not (all(STANDARD_COMMON_CLASS.match(m) for m in members) or members in confirmed_sets):
            findings.append(
                f"{concept} at {end}: classes {sorted(members)} not confirmed as all common stock"
            )
            continue
        values.append(
            XbrlValue(
                metric_id=SHARE_COUNTS[concept],
                concept=concept + SUM_OF_CLASSES,
                unit="shares",
                currency=None,
                value=sum(classes.values(), Decimal(0)),
                period_start=None,
                period_end=end,
                accession=accession,
                filed=filed,
                fiscal_period=None,
                form=form,
            )
        )
    return ClassSumResult(values, findings)
