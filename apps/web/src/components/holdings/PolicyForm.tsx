"use client";

import { useActionState, useState } from "react";

import { Metric } from "@/components/Metric";
import type { PolicyContent } from "@/lib/api";
import { ASSET_CLASSES, ASSET_CLASS_LABELS, SLEEVE_MARKETS, SLEEVE_MARKET_LABELS, membersText } from "@/lib/policy";

export interface PolicyFormState {
  errors: string[];
}

export type PolicyFormAction = (previous: PolicyFormState, form: FormData) => Promise<PolicyFormState>;

interface SleeveRow {
  id: number;
  name: string;
  asset_class: string;
  market: string;
  target_pct: string;
  band_pp: string;
  members: string;
}

const input = "rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700";
const button =
  "rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800";
const MAX_SLEEVES = 12;

function blank(id: number): SleeveRow {
  return { id, name: "", asset_class: "equity", market: "US", target_pct: "", band_pp: "", members: "" };
}

function rows(initial: PolicyContent | null): SleeveRow[] {
  if (!initial) return [blank(0)];
  return initial.sleeves.map((s, id) => ({
    id,
    name: s.name,
    asset_class: s.asset_class,
    market: s.market,
    target_pct: String(Number(s.target_pct)),
    band_pp: String(Number(s.band_pp)),
    members: membersText(s.members),
  }));
}

/**
 * Write a new version of the investment policy (M3.12, ADR-043 IP3, IP4): goals, horizon and risk
 * in your own words, and 1 to 12 sleeves whose targets add up to 100%. Starts from the version in
 * force when there is one; otherwise every target and band is empty, for you to set. Saving never
 * changes an earlier version, and nothing is ever sent to a broker.
 */
export function PolicyForm({
  initial,
  next,
  action,
}: {
  initial: PolicyContent | null;
  next: number;
  action: PolicyFormAction;
}) {
  const [state, formAction, pending] = useActionState(action, { errors: [] });
  const [sleeves, setSleeves] = useState<SleeveRow[]>(() => rows(initial));
  const total = sleeves.reduce((sum, s) => sum + (Number(s.target_pct) || 0), 0);
  const update = (id: number, field: keyof SleeveRow, value: string) =>
    setSleeves((current) => current.map((s) => (s.id === id ? { ...s, [field]: value } : s)));
  return (
    <form action={formAction} aria-label="Save a policy version" className="space-y-4 text-sm">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1">
          <span className="block">
            <Metric termId="investment_policy" icon={false}>
              Goals
            </Metric>
          </span>
          <textarea
            name="goals"
            required
            maxLength={1000}
            rows={3}
            defaultValue={initial?.goals ?? ""}
            className={`${input} w-full`}
          />
        </label>
        <label className="space-y-1">
          <span className="block">
            <Metric termId="investment_policy" icon={false}>
              Risk
            </Metric>
          </span>
          <textarea
            name="risk"
            required
            maxLength={500}
            rows={3}
            defaultValue={initial?.risk ?? ""}
            className={`${input} w-full`}
          />
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1">
          <span className="block">Horizon (years)</span>
          <input
            name="horizon_years"
            type="number"
            min="1"
            max="60"
            step="1"
            required
            defaultValue={initial?.horizon_years ?? ""}
            className={`${input} w-24`}
          />
        </label>
        <label className="space-y-1">
          <span className="block">Largest drawdown you can bear (%, optional)</span>
          <input
            name="max_drawdown_pct"
            type="number"
            min="0"
            max="100"
            step="0.01"
            defaultValue={initial?.max_drawdown_pct ? Number(initial.max_drawdown_pct) : ""}
            className={`${input} w-28`}
          />
        </label>
        <label className="space-y-1">
          <span className="block">
            <Metric termId="position_cap" icon={false}>
              Position cap (%, optional)
            </Metric>
          </span>
          <input
            name="position_cap_pct"
            type="number"
            min="0"
            max="100"
            step="0.01"
            defaultValue={initial?.position_cap_pct ? Number(initial.position_cap_pct) : ""}
            className={`${input} w-28`}
          />
        </label>
      </div>
      <fieldset className="space-y-2">
        <legend className="font-medium">
          <Metric termId="policy_sleeve">Sleeves</Metric>
        </legend>
        <p className="text-xs text-neutral-500">
          <Metric termId="policy_sleeve" icon={false}>
            {
              "Members: listings written US:SPY or TW:2330, a listing's own target after = (US:SPY=30, given for every member or none); a cash sleeve lists currencies (USD, TWD)."
            }
          </Metric>
        </p>
        <input type="hidden" name="sleeve_count" value={sleeves.length} />
        {sleeves.map((s, i) => (
          <div key={s.id} className="flex flex-wrap items-end gap-2" data-sleeve-row={i}>
            <label className="space-y-1">
              <span className="block">Name</span>
              <input
                name={`sleeve_${i}_name`}
                required
                maxLength={40}
                value={s.name}
                onChange={(e) => update(s.id, "name", e.target.value)}
                className={`${input} w-36`}
              />
            </label>
            <label className="space-y-1">
              <span className="block">Asset class</span>
              <select
                name={`sleeve_${i}_asset_class`}
                value={s.asset_class}
                onChange={(e) => update(s.id, "asset_class", e.target.value)}
                className={input}
              >
                {ASSET_CLASSES.map((c) => (
                  <option key={c} value={c}>
                    {ASSET_CLASS_LABELS[c]}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="block">Market</span>
              <select
                name={`sleeve_${i}_market`}
                value={s.market}
                onChange={(e) => update(s.id, "market", e.target.value)}
                className={input}
              >
                {SLEEVE_MARKETS.map((m) => (
                  <option key={m} value={m}>
                    {SLEEVE_MARKET_LABELS[m]}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="block">
                <Metric termId="target_weight" icon={false}>
                  Target (%)
                </Metric>
              </span>
              <input
                name={`sleeve_${i}_target_pct`}
                type="number"
                min="0"
                max="100"
                step="0.01"
                required
                value={s.target_pct}
                onChange={(e) => update(s.id, "target_pct", e.target.value)}
                className={`${input} w-24`}
              />
            </label>
            <label className="space-y-1">
              <span className="block">
                <Metric termId="rebalancing_band" icon={false}>
                  Band (± pp)
                </Metric>
              </span>
              <input
                name={`sleeve_${i}_band_pp`}
                type="number"
                min="0"
                max="50"
                step="0.01"
                required
                value={s.band_pp}
                onChange={(e) => update(s.id, "band_pp", e.target.value)}
                className={`${input} w-24`}
              />
            </label>
            <label className="min-w-[14rem] flex-1 space-y-1">
              <span className="block">Members</span>
              <input
                name={`sleeve_${i}_members`}
                required
                value={s.members}
                onChange={(e) => update(s.id, "members", e.target.value)}
                placeholder={s.asset_class === "cash" ? "USD, TWD" : "US:SPY, TW:2330"}
                className={`${input} w-full uppercase`}
              />
            </label>
            <button
              type="button"
              className={button}
              disabled={sleeves.length === 1}
              onClick={() => setSleeves((current) => current.filter((row) => row.id !== s.id))}
            >
              Remove
            </button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={button}
            disabled={sleeves.length >= MAX_SLEEVES}
            onClick={() => setSleeves((current) => [...current, blank(Math.max(...current.map((s) => s.id)) + 1)])}
          >
            Add a sleeve
          </button>
          <span className={Math.abs(total - 100) < 0.005 ? "text-neutral-400" : "text-amber-300"} data-total="">
            <Metric termId="target_weight" icon={false}>
              {`Targets add up to ${total.toFixed(2)}% (100% needed)`}
            </Metric>
          </span>
        </div>
      </fieldset>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[16rem] flex-1 space-y-1">
          <span className="block">Reason for this version</span>
          <input name="reason" required maxLength={500} className={`${input} w-full`} />
        </label>
        <button type="submit" disabled={pending} className={button}>
          {pending ? "Saving…" : (
            <Metric termId="investment_policy" icon={false}>
              {`Save as version ${next}`}
            </Metric>
          )}
        </button>
      </div>
      {state.errors.length > 0 ? (
        <ul role="alert" className="space-y-0.5 text-amber-400">
          {state.errors.map((error) => (
            <li key={error}>
              <Metric termId="investment_policy" icon={false}>
                {error}
              </Metric>
            </li>
          ))}
        </ul>
      ) : null}
    </form>
  );
}
