"""Job `finmind.history` (M3.7b, ADR-040 TW24, TW25): one code, one dataset, one date range
from FinMind, for the Taiwan history the TWSE OpenAPI cannot give (before 2026-10-21) and the
flows history. `make finmind-backfill` queues one run per code and dataset since 2016.

store, by dataset:
- TaiwanStockPrice: raw bars (feed finmind) and the price change and trade value, only for
  sessions with no TWSE row; on TWSE sessions the values are compared instead (TW19);
- TaiwanStockMarginPurchaseShortSale and TaiwanStockPER: the same measure ids as the TWSE
  files, same rule;
- TaiwanStockDividendResult: cash dividends and stock dividends the prices reproduce (TW20),
  and every ex-date's reference price (`ex_reference_price`, M3.11, ADR-042 SC6);
- TaiwanStockInstitutionalInvestorsBuySell and TaiwanStockShareholding: every session.
Re-running is harmless: stored values are unchanged, changed ones become revisions (TW18).
"""

import json
from datetime import date
from typing import Any, ClassVar

from autotrading.adapters.finmind.client import (
    ALLOWED_DATASETS,
    DIVIDENDS,
    INSTITUTIONAL,
    MARGIN,
    PER,
    PRICE,
    SHAREHOLDING,
    SOURCE_ID,
    FinMindClient,
)
from autotrading.adapters.finmind.store import Writer
from autotrading.domain.finmind import (
    dividend_results,
    flow_days,
    margin_days,
    price_rows,
    shareholding_days,
    valuation_rows,
)
from autotrading.ingestion.job import (
    FetchContext,
    FetchedPayload,
    IngestionJob,
    StoreContext,
    StoreResult,
    register_job,
)
from autotrading.repositories.universe import taiwan_universe

HISTORY_START = date(2016, 1, 1)


@register_job
class FinMindHistoryJob(IngestionJob):
    source_id: ClassVar[str] = SOURCE_ID
    name: ClassVar[str] = "finmind.history"
    feed_status: ClassVar[str] = "end_of_day"
    data_mode: ClassVar[str] = "live"

    def client(self) -> FinMindClient:
        return FinMindClient.from_settings()

    @property
    def code(self) -> str:
        return str(self.params["code"])

    @property
    def dataset(self) -> str:
        dataset = str(self.params["dataset"])
        if dataset not in ALLOWED_DATASETS:
            raise ValueError(f"{dataset} is not a FinMind dataset this source uses")
        return dataset

    def fetch(self, ctx: FetchContext) -> list[FetchedPayload]:
        start = date.fromisoformat(str(self.params["start"]))
        end = date.fromisoformat(str(self.params["end"]))
        with self.client() as client:
            return [client.get(self.dataset, self.code, start, end, ctx.acquire)]

    def store(self, ctx: StoreContext) -> StoreResult:
        code, dataset = self.code, self.dataset
        writer = Writer(ctx, [code], feed_status=self.feed_status, data_mode=self.data_mode)
        if code not in writer.ids:
            return StoreResult(
                0, 0, notes=(f"no instrument yet for {code} (run make twse-refresh first)",)
            )
        etf = code in taiwan_universe().etfs
        for payload in ctx.payloads:
            body: Any = json.loads(payload.content)
            if dataset == PRICE:
                rows = price_rows(body)
                if rows:
                    writer.notes.append(f"{code}: FinMind closes from {rows[0].session}")
                kept = writer.bars(code, rows, payload)
                writer.day_measures(code, kept, payload)
                # the price change and trade value of TWSE sessions, compared (TW19)
                writer.compare_only(
                    code,
                    [
                        (r.session, measure_id, value)
                        for r in rows
                        if r not in kept
                        for measure_id, value in (
                            ("price_change", r.change),
                            ("trade_value", r.value),
                        )
                        if value is not None
                    ],
                )
            elif dataset == MARGIN:
                writer.margin(code, margin_days(body), payload)
            elif dataset == PER:
                writer.valuation(code, valuation_rows(body), payload)
            elif dataset == DIVIDENDS:
                results = dividend_results(body, etf=etf)
                writer.dividends(code, results, payload)
                writer.reference_prices(code, results, payload)
            elif dataset == INSTITUTIONAL:
                days, notes = flow_days(body)
                writer.notes += notes
                writer.flows(code, days, payload)
            elif dataset == SHAREHOLDING:
                writer.shareholding(code, shareholding_days(body), payload)
        return StoreResult(
            inserted=writer.inserted,
            unchanged=writer.unchanged,
            conflicted=len(writer.conflicts),
            notes=tuple(writer.finish_notes() + writer.conflicts),
        )
