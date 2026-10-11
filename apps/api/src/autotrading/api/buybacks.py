"""Buyback API (M1.4a, ADR-025): a universe equity's authorizations, actual repurchases and net
share reduction, kept apart (02 §5), as known at a time. Read-only.

- Announcements: authorization, plan and remaining-amount statements from 8-Ks and press
  releases, grouped into events, each with its sentence and link (api/buyback_announcements).
- As tagged: the latest XBRL repurchase_authorized and repurchase_remaining of 10-Q/10-K, which
  only corroborate (they are known at filing acceptance and mean different things per company).
- Per period: repurchases, intensity, funding, SBC offset, debt-funded flag, net share reduction
  and diluted share change, each with its inputs and filings.
- State (M1.4b): the latest stored assignment at or before T and the state history
  (api/buyback_states).
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from autotrading.api.buyback_announcements import (
    AnnouncementEvent,
    announcement_sources,
    event_out,
)
from autotrading.api.buyback_states import (
    StateAssignmentOut,
    StatePoint,
    active_rule_version,
    stored_states,
)
from autotrading.api.data_health import SessionDep
from autotrading.api.instruments import FactView, issuer_chain
from autotrading.api.research import KnownAt, ResearchPeriod
from autotrading.api.valuation import (
    InputOut,
    MetricOut,
    filing_forms,
    input_out,
    known_at_or_now,
    market_view,
    metric_out,
    universe_equity,
)
from autotrading.domain.buyback import (
    BUYBACK_METRICS,
    Section,
    buyback_record,
    events,
)
from autotrading.domain.buyback_announcements import EXTRACTOR_VERSION
from autotrading.domain.valuation import Input, Unit

router = APIRouter(tags=["buybacks"])

TAGGED_METRICS = ("repurchase_authorized", "repurchase_remaining")
HISTORY_YEARS = 6  # closes for five fiscal year ends and the latest quarter


class BuybackRow(BaseModel):
    metric_id: str
    section: Section
    unit: Unit
    cells: list[MetricOut]  # one per period, in the order of `periods`


class BuybacksOut(BaseModel):
    ticker: str
    known_at: datetime
    extractor_version: str
    rule_version: str  # of the state below: the active rule set (M1.4b)
    state: StateAssignmentOut | None  # the latest stored at or before T
    state_history: list[StatePoint]  # oldest first
    announcements: list[AnnouncementEvent]  # newest first
    tagged_authorized: InputOut | None  # latest XBRL authorization, as the filing tags it
    tagged_remaining: InputOut | None
    periods: list[ResearchPeriod]
    rows: list[BuybackRow]


def _latest(facts: list[FactView], metric: str) -> Input[FactView] | None:
    found = [f for f in facts if f.metric_id == metric and f.period_start is None]
    if not found:
        return None
    latest = max(found, key=lambda f: (f.period_end, f.reported_at))
    return Input(
        metric, latest.value, None, latest.period_end, (latest,), "as tagged in the filing"
    )


@router.get("/instruments/{ticker}/buybacks")
def instrument_buybacks(ticker: str, session: SessionDep, known_at: KnownAt = None) -> BuybacksOut:
    instrument = universe_equity(session, ticker)
    assert instrument.entity_id is not None
    at = known_at_or_now(session, known_at)
    chain = issuer_chain(session, instrument.entity_id)
    view = market_view(
        session,
        instrument,
        chain.order,
        at,
        (*BUYBACK_METRICS, *TAGGED_METRICS),
        bars_since=datetime(at.year - HISTORY_YEARS, 1, 1, tzinfo=UTC),
    )
    record = buyback_record(view.facts, view.closes, at, view.splits)
    tagged = {m: _latest(view.facts, m) for m in TAGGED_METRICS}
    found_events = events(announcement_sources(session, instrument, chain.order, at), at)
    forms = filing_forms(
        session,
        [
            *(f for *_, values in record.rows for v in values for i in v.inputs for f in i.sources),
            *(f for i in tagged.values() if i is not None for f in i.sources),
        ],
    )
    rule_version = active_rule_version()
    state, history = stored_states(session, instrument.id, at, rule_version)
    return BuybacksOut(
        ticker=ticker.upper(),
        known_at=at,
        extractor_version=EXTRACTOR_VERSION,
        rule_version=rule_version,
        state=state,
        state_history=history,
        announcements=[event_out(e) for e in found_events],
        tagged_authorized=input_out(i, forms) if (i := tagged["repurchase_authorized"]) else None,
        tagged_remaining=input_out(i, forms) if (i := tagged["repurchase_remaining"]) else None,
        periods=[
            ResearchPeriod(kind=w.kind, period_start=w.start, period_end=w.end)
            for w in record.periods
        ],
        rows=[
            BuybackRow(
                metric_id=metric,
                section=section,
                unit=unit,
                cells=[metric_out(v, forms) for v in values],
            )
            for section, metric, unit, values in record.rows
        ],
    )
