# Phase 3 — Policy, events and the world: causal evidence without execution

**Status:** Approved 2026-10-19 (ADR-035): Steven answered P3-1 to P3-6 with the proposed defaults and decided OD-6 (P3-5). Proposed by Claude on 2026-10-18 with the Phase 2 exit report (`docs/reports/phase2_exit.md`). The entry gate is met: the Phase 2 exit (#31) and ADR-009 accepted (ADR-034). Order: M3.0 carry-overs, then policy, the causal graph and the physical data (ADR-034 E4). Each sub-milestone still starts in plan mode; Claude decides its scope and thresholds (ADR-035).

**Goal:** turn official policy actions and news events into cited, time-stamped evidence about who is exposed, without ever trading on a headline:
- a Policy Monitor that follows each US policy action through its lifecycle, from official sources only;
- language-model extraction and linking under a hard budget, every call logged and every field cited (ADR-009);
- news stories clustered into events and linked to the companies they concern;
- an Event Transmission graph from events and policies to goods, sectors, companies and instruments, where every edge has evidence and a timestamp;
- physical data and the Global Monitor once OD-6 is decided.

**Phase 3 exit criteria** (ROADMAP, 02 §29, 01 §29):
- ROADMAP: "Every graph edge has evidence + timestamp; policy lifecycle correct; no execution path from a headline."
- 02 §29: "Causal evidence; policy lifecycle; no event-only execution."
- 01 §29: "causal evidence; policy lifecycle correctness; no direct execution from headline."

**Entry gate:** "Phase 2 exit; ADR-009 accepted" (ROADMAP). Met: ADR-009 accepted on 2026-10-18 (ADR-034), the Phase 2 exit merged on 2026-10-18 (#31).

**Out of scope for Phase 3:**
- **Phase 4:** X, Congress PTR, Form 4 insiders.
- **Phases 5–6:** options, any broker or order path, live trading. S5 (event / supply chain) and S9 (political headlines) stay alert-only; no event or headline makes a TRADE, a TRADE-READY or an L4.
- **OD-3:** consensus estimates and S2.
- **OD-7:** backtest performance stays withheld.
- **Cloud and sign-in:** local only (ADR-034).
- **Language models deciding anything:** they extract, link and summarize; valuation, factors, risk, sizing and eligibility stay deterministic (02 §24).

Work one sub-milestone at a time, in order. Each one ends with the Build Output Contract and a `docs/STATUS.md` update. Every new metric, rule and page ships with its glossary entry and Chinese hint in the same PR.

---

## Decisions (all decided 2026-10-19, ADR-035)

| # | Question | Proposed default |
|---|---|---|
| P3-1 | **Policy sources:** which official sources feed the Policy Monitor? Adding a provider needs Steven's approval. | **Decided 2026-10-19 (ADR-035): as proposed.** The White House actions feed (already ingested) and the **Federal Register API** (free, official, no key): executive orders, proclamations and the notices of USTR, Commerce (BIS export controls) and Treasury. USTR press releases by RSS. OFAC sanctions lists later. |
| P3-2 | **Language-model tasks and evaluation** | **Decided 2026-10-19 (ADR-035): as proposed.** Two tasks only: (1) extract a policy object from an official document (status, effective date, affected goods, sectors, countries and the universe instruments), each field with the sentence it came from; (2) link a news event to universe companies, with the sentence. A small, cheap model by default (from `LLM_MODEL`), a larger one only when the small one is unsure. A labelled evaluation set of about 50 documents and 50 events, released as a version; a prompt or model change is a new version with its evaluation. Target: at least 90% correct status and effective date, and no uncited field. |
| P3-3 | **Policy scope** | **Decided 2026-10-19 (ADR-035): as proposed.** Tariffs, export controls (semiconductors and other critical technology), sanctions and critical minerals. Mapped to the 10 companies and 8 ETFs through a reviewed table of goods and sectors, for example NVDA with export controls, XOM and XLE with energy sanctions, LOW, AZO and ORLY with tariffs on imported goods. |
| P3-4 | **Causal graph edges** | **Decided 2026-10-19 (ADR-035): as proposed.** Node types: event, policy, good or sector, company, instrument. Edge types: triggers, affects, exposes, confirmed by price. Every edge cites a source sentence or a stored row and has a timestamp. Exposure is a range (low, base, high), never one forecast. Price confirmation reads the stored factor snapshots. Edges proposed by rules or extraction are marked as such. |
| P3-5 | **OD-6 physical data** | **Decided 2026-10-19 (ADR-035): as proposed.** NASA FIRMS active fires (free, a key in `.env`) and NOAA's ENSO index (free), for energy and agriculture exposure. Shipping and port data stay out (paid vendors). The Global Monitor shows `Data unavailable` for any layer not decided. |
| P3-6 | **Phase 2 carry-overs before the new features** | **Decided 2026-10-19 (ADR-035): as proposed.** A short **M3.0**: regime rules 0.2.0 (KI-3, KI-4, KI-5, KI-7: credit fallback, the NFCI threshold, VIX alone, the stagflation band) with a backfill and the alerts raised again, and S4's daily assessment with family 5 signals and Radar candidates (KI-21). Risk rules 0.2.0 (KI-13, KI-20) wait for OD-7. |

---

## M3.0 Phase 2 carry-overs
**Build**
- **Regime rules 0.2.0:** the thresholds Steven reviews against the history since 2016 (KI-3, KI-4, KI-5, KI-7), a backfill under the new version, rotation and alerts recomputed on it.
- **S4 daily:** the momentum assessment stored daily, family 5 signals for S4, S4 candidates on the Opportunity Radar.

**Acceptance**
- [ ] Regime rules 0.2.0 recompute identically as known on their dates; 0.1.0 is kept and its rows unchanged.
- [ ] S4 signals cite their rule version and factor snapshots, as S3's do.

## M3.1 Language-model foundation (ADR-009)
**Build**
- **One client:** every call goes through one wrapper reading `ANTHROPIC_API_KEY` and `LLM_MODEL` from the settings; feature code never calls the API directly (tested).
- **Usage ledger:** every call stored with its time, model, purpose, input and output tokens, estimated cost and the object IDs it served; append-only.
- **Budget:** USD 50 a month; alerts at 70%, 90% and 100% in the Alerts Center; at 100% a circuit breaker refuses every call until the next month.
- **Extraction contract:** versioned prompts and JSON schemas; every extracted field carries the sentence it came from; an evaluation harness on the labelled set (P3-2).

**Acceptance**
- [ ] Every call is in the ledger with its cost; at 100% of the budget no call is made (tested with a fake client).
- [ ] An extraction without a cited sentence is rejected; the evaluation result is stored with the prompt version.

## M3.2 Policy Monitor
**Build**
- **Sources** (P3-1): the Federal Register API and the White House actions feed, stored with provenance like every other source.
- **Policy objects:** status, jurisdiction, affected goods, sectors and countries, effective date, implementation status, direct and second-order exposure, linked instruments and evidence URLs (02 §7).
- **Lifecycle:** statement, proposal, signed action, effective, implementation, challenged or modified, expired or replaced. A state changes only on an official document; a statement never counts as effective (01 §6).
- **Policy Monitor dashboard** with As known on, and policy alerts (a new alert rule version).

**Acceptance**
- [ ] The lifecycle is correct on the labelled sample; every state cites its official document and time.
- [ ] A statement or proposal never enters the causal model as an effective policy.

## M3.3 News events and company links
**Build**
- **Events:** syndicated stories clustered into one event (a repost chain is one source; 02 §8), with the earliest time and every outlet.
- **Links:** events linked to universe companies by rules first, then the language model with the cited sentence (deferred in ADR-018).

**Acceptance**
- [ ] A repost chain counts as one source; an event's links cite their text.

## M3.4 Event Transmission graph
**Build**
- **Graph** (P3-4): nodes and edges from policies, events, goods and sectors to companies and instruments, each edge with its evidence and timestamp, as known at T.
- **Exposure ranges and price confirmation** from the stored factor snapshots; the outputs are thesis candidates only.
- **Event Transmission dashboard;** S5 and S9 alerts (alert-only).

**Acceptance**
- [ ] Every edge has evidence and a timestamp; the graph as known on a past date is reproducible.
- [ ] No path leads from an event or headline to a TRADE, a TRADE-READY or an L4 (tested, like the no-order test).

## M3.5 Physical data and the Global Monitor (OD-6)
**Build**
- **Sources** (P3-5): NASA FIRMS and the NOAA ENSO index, with provenance.
- **Global Monitor:** a map of current signals, sources, entities, transmission paths and instruments (02 §21); `Data unavailable` for any layer not decided.

**Acceptance**
- [ ] Every layer cites its source and time; no physical reading reaches a decision without the causal graph.

## M3.6 Phase 3 exit report
Write `docs/reports/phase3_exit.md` in the format of `phase2_exit.md`. Then propose `docs/milestones/M4_*.md` for approval.
