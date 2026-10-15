"use client";

import { useActionState, useState } from "react";

import { Metric } from "@/components/Metric";
import type { EvidenceItem, Signal, ThesisCard } from "@/lib/api";
import { EVIDENCE_KINDS, NO_TRADE_REASONS, type EvidenceKind, evidenceValue } from "@/lib/journal";
import { formatSgtEt } from "@/lib/time";

export interface JournalFormState {
  errors: string[];
}

export type JournalFormAction = (previous: JournalFormState, form: FormData) => Promise<JournalFormState>;

const MIN_EVIDENCE = 3;
const MAX_EVIDENCE = 7;
const CATALYST_ROWS = [0, 1, 2, 3, 4];
const input = "w-full rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700";

/** "financial_fact:<id>" or "price_close:<day>": one cited row. */
export function evidenceKey(item: Pick<EvidenceItem, "kind" | "ref">): string {
  return `${item.kind}:${item.ref.id ?? item.ref.day}`;
}

function Candidate({
  item,
  checked,
  onToggle,
}: {
  item: EvidenceItem;
  checked: boolean;
  onToggle: (on: boolean) => void;
}) {
  const key = evidenceKey(item);
  const quoted = item.kind === "buyback_statement" || item.kind === "guidance_statement" || item.kind === "news";
  return (
    <li className="space-y-1 rounded border border-neutral-800 px-3 py-2">
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          name="evidence"
          aria-label={item.label}
          value={JSON.stringify({ kind: item.kind, ...item.ref })}
          checked={checked}
          onChange={(event) => onToggle(event.target.checked)}
          className="mt-1"
        />
        <span className="space-y-0.5">
          <span className="block text-neutral-200">
            <Metric termId={EVIDENCE_KINDS[item.kind].termId} icon={false}>
              {item.label}
            </Metric>
          </span>
          {quoted ? (
            <q data-quoted="" className="block text-xs text-neutral-400">
              {item.summary}
            </q>
          ) : (
            <span className="block text-xs text-neutral-400">
              <Metric termId="evidence_item" icon={false}>
                {evidenceValue(item)} · public {formatSgtEt(item.published_at)}
              </Metric>
            </span>
          )}
        </span>
      </label>
      {checked ? (
        <input
          name={`note:${key}`}
          aria-label="Why it matters (optional)"
          placeholder="Why it matters (optional)"
          maxLength={200}
          defaultValue={item.note ?? ""}
          className={`${input} text-xs`}
        />
      ) : null}
    </li>
  );
}

/**
 * Thesis Card form (M1.6, ADR-027): a new card with its decision, or a new version of a card.
 * Evidence is picked from rows the API lists for the company (3 to 7); the server reads each
 * again and stores it as known now. Works without client JavaScript: the server action reloads.
 */
export function EntryForm({
  ticker,
  candidates,
  signals,
  selectedSignal,
  card,
  action,
}: {
  ticker: string;
  candidates: EvidenceItem[];
  signals: Signal[];
  selectedSignal?: string;
  /** The latest version of the card, to write a new version of it. */
  card?: ThesisCard;
  action: JournalFormAction;
}) {
  const [state, formAction, pending] = useActionState(action, { errors: [] });
  const cited = card ? card.evidence : [];
  const items = [...cited, ...candidates.filter((c) => !cited.some((e) => evidenceKey(e) === evidenceKey(c)))];
  const [checked, setChecked] = useState<Set<string>>(new Set(cited.map(evidenceKey)));
  const [decision, setDecision] = useState<"no_trade" | "trade">("no_trade");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const groups = (Object.keys(EVIDENCE_KINDS) as EvidenceKind[])
    .map((kind) => ({
      kind,
      items: items.filter((item) => item.kind === kind),
    }))
    .filter((group) => group.items.length > 0);
  const toggle = (key: string, on: boolean) =>
    setChecked((previous) => {
      const next = new Set(previous);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  const count = checked.size;
  return (
    <form action={formAction} aria-label={card ? "New version" : "New Thesis Card"} className="space-y-5 text-sm">
      <input type="hidden" name="ticker" value={ticker} />
      {card ? <input type="hidden" name="card_id" value={card.card_id} /> : null}

      <label className="block space-y-1">
        <span className="block font-medium">
          <Metric termId="thesis_card">Thesis</Metric>
        </span>
        <textarea name="thesis" aria-label="Thesis" required maxLength={400} rows={2} defaultValue={card?.thesis} className={input} />
      </label>

      <fieldset className="space-y-2">
        <legend className="font-medium">
          <Metric termId="evidence_item">Evidence</Metric>
        </legend>
        <p
          className={`text-xs ${count < MIN_EVIDENCE || count > MAX_EVIDENCE ? "text-amber-400" : "text-neutral-400"}`}
          aria-live="polite"
        >
          <Metric termId="evidence_item" icon={false}>
            {count} selected; pick {MIN_EVIDENCE} to {MAX_EVIDENCE}. Each is stored as known now.
          </Metric>
        </p>
        {groups.map((group) => (
          <div key={group.kind} className="space-y-1">
            <h3 className="text-xs uppercase tracking-wide text-neutral-500">{EVIDENCE_KINDS[group.kind].label}</h3>
            <ul className="space-y-1" aria-label={EVIDENCE_KINDS[group.kind].label}>
              {group.items.map((item) => (
                <Candidate
                  key={evidenceKey(item)}
                  item={item}
                  checked={checked.has(evidenceKey(item))}
                  onToggle={(on) => toggle(evidenceKey(item), on)}
                />
              ))}
            </ul>
          </div>
        ))}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="font-medium">
          <Metric termId="catalyst">Catalysts</Metric>
        </legend>
        {CATALYST_ROWS.map((i) => (
          <div key={i} className="flex flex-wrap gap-2">
            <input
              name="catalyst_description"
              aria-label="Catalyst"
              placeholder={i === 0 ? "Event that could reprice the stock" : "Another catalyst (optional)"}
              maxLength={200}
              defaultValue={card?.catalysts[i]?.description ?? ""}
              className={`${input} min-w-0 flex-1`}
            />
            <input
              name="catalyst_expected"
              type="date"
              aria-label="Expected date"
              defaultValue={card?.catalysts[i]?.expected ?? ""}
              className="rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
            />
          </div>
        ))}
      </fieldset>

      <label className="block space-y-1">
        <span className="block font-medium">
          <Metric termId="invalidation">Invalidation</Metric>
        </span>
        <textarea
          name="invalidation"
          aria-label="Invalidation"
          required
          maxLength={500}
          rows={2}
          placeholder="What would prove the thesis wrong"
          defaultValue={card?.invalidation}
          className={input}
        />
      </label>

      <label className="block space-y-1">
        <span className="block font-medium">Notes (not evidence)</span>
        <textarea name="notes" aria-label="Notes" maxLength={2000} rows={2} defaultValue={card?.notes ?? ""} className={input} />
      </label>

      {signals.length > 0 ? (
        <fieldset className="space-y-1">
          <legend className="font-medium">
            <Metric termId="signal">Signals</Metric>
          </legend>
          {signals.map((signal) => (
            <label key={signal.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                name="signal"
                aria-label={`Signal ${signal.ticker} ${signal.state}`}
                value={signal.id}
                defaultChecked={signal.id === selectedSignal || card?.signal_ids.includes(signal.id)}
              />
              <Metric termId="signal" icon={false}>
                {signal.ticker} {signal.state.replace("_", "-").toUpperCase()} under rules {signal.rule_version},{" "}
                {formatSgtEt(signal.generated_at)}
              </Metric>
            </label>
          ))}
        </fieldset>
      ) : null}

      {card ? null : (
        <fieldset className="space-y-2 rounded border border-neutral-800 p-3">
          <legend className="px-1 font-medium">
            <Metric termId="trade_decision">Decision</Metric>
          </legend>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="decision"
                value="no_trade"
                checked={decision === "no_trade"}
                onChange={() => setDecision("no_trade")}
              />
              <Metric termId="no_trade" icon={false}>
                NO TRADE
              </Metric>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="decision"
                value="trade"
                checked={decision === "trade"}
                onChange={() => setDecision("trade")}
              />
              <Metric termId="trade_decision" icon={false}>
                Paper TRADE
              </Metric>
            </label>
          </div>
          {decision === "no_trade" ? (
            <label className="block space-y-1">
              <span className="block">Reason</span>
              <select name="no_trade_reason" defaultValue="priced_in" className={input}>
                {Object.entries(NO_TRADE_REASONS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <label className="space-y-1">
                <span className="block">Side</span>
                <select name="side" defaultValue="buy" className={input}>
                  <option value="buy">Buy</option>
                  <option value="sell">Sell (short)</option>
                </select>
              </label>
              <label className="space-y-1">
                <span className="block">Shares</span>
                <input name="quantity" type="number" min="0.0001" step="any" required className={input} />
              </label>
              <label className="space-y-1">
                <span className="block">Order type</span>
                <select
                  name="order_type"
                  value={orderType}
                  onChange={(event) => setOrderType(event.target.value as "market" | "limit")}
                  className={input}
                >
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                </select>
              </label>
              {orderType === "limit" ? (
                <label className="space-y-1">
                  <span className="block">Limit price (USD)</span>
                  <input name="limit_price" type="number" min="0.01" step="0.01" required className={input} />
                </label>
              ) : null}
              <label className="space-y-1">
                <span className="block">
                  <Metric termId="max_loss" icon={false}>
                    Maximum loss (USD)
                  </Metric>
                </span>
                <input name="max_loss" type="number" min="0.01" step="0.01" required className={input} />
              </label>
            </div>
          )}
          <label className="block space-y-1">
            <span className="block">Note {decision === "no_trade" ? "(needed for Other)" : "(optional)"}</span>
            <input name="decision_note" maxLength={1000} className={input} />
          </label>
          <p className="text-xs text-neutral-500">
            <Metric termId="paper_mode" icon={false}>
              Paper only: a TRADE enters at the last end-of-day close known now; nothing is sent.
            </Metric>
          </p>
        </fieldset>
      )}

      {state.errors.length > 0 ? (
        <ul role="alert" className="space-y-0.5 text-amber-400">
          {state.errors.map((error) => (
            <li key={error}>
              <Metric termId={error.includes("vetoed by risk rules") ? "risk_veto" : "thesis_card"} icon={false}>
                {error}
              </Metric>
            </li>
          ))}
        </ul>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        {pending ? "Saving…" : card ? "Save as a new version" : "Save Thesis Card"}
      </button>
      <p className="text-xs text-neutral-500">
        Cards and decisions are never changed or deleted; each save is recorded in the Audit Log.
      </p>
    </form>
  );
}
