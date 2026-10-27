"""Job `finmind.flows` (M3.7b, ADR-040 TW25): the Taiwan universe's institutional investors and
foreign shareholding of the last days, once a day at 21:30 Singapore time.

fetch: TaiwanStockInstitutionalInvestorsBuySell and TaiwanStockShareholding per code over a
window of the last 10 days (FinMind revises recent days), and TaiwanStockPrice for the codes the
refresh found a calendar session without a stored close for (a lost TWSE session, KI-27).
store: net buying by group and the foreign holding per session into exchange_measures
(source finmind, tier 2); a changed value for a session already stored becomes a revision
public at the end of the fetch day (TW18); closes only for sessions with no TWSE bar (TW24).
Codes without an instrument yet (the TWSE job creates them) are noted and skipped.
"""

import json
from datetime import date
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from autotrading.adapters.finmind.client import (
    INSTITUTIONAL,
    PRICE,
    SHAREHOLDING,
    SOURCE_ID,
    FinMindClient,
)
from autotrading.adapters.finmind.store import Writer
from autotrading.domain.finmind import flow_days, price_rows, shareholding_days
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoredPayload,
    StoreResult,
    register_job,
)


def dataset_of(payload: StoredPayload) -> tuple[str, str]:
    """(dataset, code) a payload was fetched for, from its request URL."""
    query = parse_qs(urlparse(payload.source_url).query)
    return query["dataset"][0], query["data_id"][0]


@register_job
class FinMindFlowsJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "finmind.flows"
    feed_status: ClassVar[str] = "end_of_day"  # fixture for recorded test data
    data_mode: ClassVar[str] = "live"

    def client(self) -> FinMindClient:
        return FinMindClient.from_settings()

    @property
    def codes(self) -> list[str]:
        return [str(c) for c in self.params["codes"]]

    @property
    def dates(self) -> tuple[date, date]:
        return date.fromisoformat(str(self.params["start"])), date.fromisoformat(
            str(self.params["end"])
        )

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        start, end = self.dates
        price_codes = {str(c) for c in self.params.get("price_codes", [])}
        payloads = []
        with self.client() as client:
            for code in self.codes:
                for dataset in (INSTITUTIONAL, SHAREHOLDING):
                    payloads.append(client.get(dataset, code, start, end, ctx.acquire))
                if code in price_codes:
                    payloads.append(client.get(PRICE, code, start, end, ctx.acquire))
        return payloads

    def store(self, ctx: StoreContext) -> StoreResult:
        writer = Writer(ctx, self.codes, feed_status=self.feed_status, data_mode=self.data_mode)
        missing = sorted(set(self.codes) - set(writer.ids))
        if missing:
            writer.notes.append(
                f"no instrument yet for {', '.join(missing)} (the TWSE job creates them); skipped"
            )
        for payload in ctx.payloads:
            dataset, code = dataset_of(payload)
            body: Any = json.loads(payload.content)
            if dataset == INSTITUTIONAL:
                days, notes = flow_days(body)
                writer.notes += notes
                writer.flows(code, days, payload)
            elif dataset == SHAREHOLDING:
                writer.shareholding(code, shareholding_days(body), payload)
            elif dataset == PRICE:
                rows = price_rows(body)
                kept = writer.bars(code, rows, payload)
                writer.day_measures(code, kept, payload)
        return StoreResult(
            inserted=writer.inserted,
            unchanged=writer.unchanged,
            conflicted=len(writer.conflicts),
            notes=tuple(writer.finish_notes() + writer.conflicts),
        )
