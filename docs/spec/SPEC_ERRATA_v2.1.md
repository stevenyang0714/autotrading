# SPEC ERRATA v2.1 (overrides 01 and 02 v2 where they conflict)

Date: 2026-10-04. Scope: conflicts and gaps found when reviewing `01_research_report_v2.md` and `02_master_build_prompt_v2.md` before build start. Every item below is binding unless superseded by a later errata or ADR.

## E1. Data contracts — use the superset of 01 §28 and 02 §28

The two documents list slightly different minimum fields. The canonical contract is the union:

| Object | Resolution |
|---|---|
| MarketPriceObservation | Add `symbol` and `adjustment_status` (raw / split_adjusted / total_return_adjusted) from 01. `feed_status` is an enum, see E4. |
| FinancialFact | Use 01 wording: `vintage` plus revision metadata (`supersedes_fact_id`, `revision_reason`). |
| Signal | `strategy_id` is **nullable** (L0/L1 signals from source streams belong to a family, not a strategy). Include `valid_from` (present in 01 §28 and 02 §25, missing in 02 §28). |
| TradeDecision | Include `created_at` and `user_id` (from 01) in addition to the 02 timestamp fields. Single-user today, but keep the column. |
| NewsEvent | Field is `source_tier` (01 naming), not `tier`. |
| InsiderTrade | `10b5-1_flag` is stored as `is_10b5_1` nullable boolean: true / false / null = not disclosed or not parsed. UI shows Yes / No / Unknown. |

All objects additionally carry the common provenance fields from 02 §4 and `created_at`, `updated_at`, `version`.

## E2. Source Tier direction

02 §32.1 says "Higher tier = stronger source quality". That is ambiguous and contradicts 02 §4 / 01 §20, where Tier 1 is the strongest. Canonical rule: **Tier 1 = strongest, Tier 4 = weakest. A lower tier number means stronger evidence.** The glossary entry `source_tier` uses this wording.

## E3. Composite scores

No composite score that mixes Risk Score (higher = worse) with positive-direction scores is built in Phases 0–2. If one is introduced later it needs an ADR with the explicit normalization formula and its own glossary entry.

## E4. Feed status enum (no mock-live confusion)

`feed_status` ∈ `live_consolidated`, `live_single_venue` (e.g. IEX-only), `delayed`, `end_of_day`, `stale`, `unavailable`, `fixture`, `demo`.
- The UI must always show the feed status badge next to any price.
- `fixture` and `demo` are never allowed in the execution path and must render with a visible banner.
- A quote older than its configured freshness SLA becomes `stale` and blocks any execution-eligibility check.

## E5. Phase 0 "real market data" exit criterion

Satisfied by the Alpaca Basic feed (IEX real-time, single venue) with `feed_status = live_single_venue` clearly shown (see ADR-004). Massive remains the canonical primary provider and is activated after the license check.

## E6. Data that has no provider yet (agent must not guess one)

02 says the agent must not replace or invent providers. These datasets have **no provider assigned** in v2. Until the matching open decision in DECISIONS.md is closed, the related fields are stored as null and displayed as `Data unavailable` — never estimated or scraped:

| Dataset | Needed for | Open decision |
|---|---|---|
| Point-in-time analyst consensus, revisions, dispersion | S2, Earnings engine (Phase 1) | OD-3 |
| Options chains, IV, Greeks | S6, Options engine (Phase 5) | OD-4 |
| Short interest, borrow fee/availability | Family 7, SHORT eligibility | OD-5 |
| Weather, fire, shipping, port data | Family 8, S5 (Phase 3) | OD-6 |
| Survivorship-free history incl. delisted names | All backtests (Phase 2) | OD-7 |

Phase 1 earnings work without OD-3 is limited to: actual vs prior period / YoY from SEC filings, guidance text extraction from 8-K exhibits, and post-event price reaction. Consensus-based surprise is shown as unavailable.

## E7. Buyback alert states need explicit entry rules

02 §5 lists BUYBACK WATCH / ACTIVE / HIGH-CONVICTION CANDIDATE / TRADE-READY without entry criteria. Before Phase 1 implementation, the Phase 1 milestone file must define each state as a versioned, deterministic rule (inputs, thresholds, required evidence), and each state gets a glossary entry. Announcement alone can reach WATCH at most.

## E8. External access requirements missing from v2

- SEC EDGAR (data.sec.gov): every request sends a `User-Agent` header with the user's name and email (`SEC_USER_AGENT`); throttle well below 10 requests/second; cache aggressively; respect 403/429 with backoff.
- FRED/ALFRED: requires a free API key (`FRED_API_KEY`); use `realtime_start` / `realtime_end` for vintages.
- GDELT and RSS: respect published rate limits and robots/terms; store metadata and short snippets only.

## E9. Universe

v2 does not define an initial instrument universe. Phase 0 uses `config/universe.yaml` (user-editable, small, bounded API usage). The seed list exists for data-coverage testing only and is not an investment view.

## E10. Single-user, non-redistribution scope

v2 mixes personal-tool and customer-facing (redistribution) language. Phases 0–6 are a **single-user personal tool with no redistribution of market data** (ADR-001). Any multi-user or customer-facing scope requires a new ADR plus a license review (Massive Business tier, news licensing).

## E11. Missing budget lines

Add to 02 §27.1: **LLM API usage** — proposed MVP cap USD 50/month with usage ledger and 70/90/100% alerts (ADR-009). Options, consensus and short-interest data have no budget yet (see E6).

## E12. Deployment safety

A deployed instance must never be reachable without authentication. Until a deployment ADR exists, the stack runs locally only.

## E13. Glossary scope includes dashboard labels and planned-phase labels

01 §22 requires a `?` on dashboard labels; 02 §22 and CLAUDE.md list metrics, scores, badges, statuses, risk measures and strategies only. Resolution (approved by Steven, 2026-10-04): use the stricter 01 scope.
- The 15 dashboard labels (02 §21) and the `planned_phase` status label ("Planned — Phase N") each get a glossary entry.
- The entries and the switch to `<Metric>` / glossary rendering land in M0.4. In M0.1 the nav and planned pages render plain text, because the glossary component does not exist yet.

## E14. Strategy registry wording and fact-table timestamps

Approved by Steven, 2026-10-05 (M0.2 plan).
- **Strategy unlock conditions:** 02 §18 (the strategy registry) and 02 §30 (the permission matrix) word the same conditions slightly differently, e.g. S2 "OOS + event timing + cost" vs "OOS + event-timing + costs". The `strategies` table uses the §18 wording. The meaning is the same; §30 is treated as an abbreviation.
- **Fact-table timestamps:** E1 requires `created_at`, `updated_at` and `version` on every object; ADR-007 names system time `recorded_at` / `superseded_at`. On append-only fact tables, `created_at` ≡ `recorded_at`, the only possible update is setting `superseded_at` (ADR-012), and `version` numbers the versions of one fact key. No duplicate columns are added. Mutable tables (sources, entities, instruments, identifiers) carry `created_at`, `updated_at` and `version`, maintained by a trigger.
