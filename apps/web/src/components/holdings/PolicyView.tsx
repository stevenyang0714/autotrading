import Link from "next/link";
import type { ReactNode } from "react";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { InstrumentName } from "@/components/InstrumentName";
import { Metric } from "@/components/Metric";
import type { CompleteTermId } from "@/generated/glossary";
import type { PolicyAssessment, PolicyVersions } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { FLAG_LABELS, FLAG_TERMS, money, quantity, signedMoney, weight } from "@/lib/holdings";
import {
  ASSET_CLASS_LABELS,
  BLOCKED_LABELS,
  BLOCKED_TERMS,
  SIDE_LABELS,
  SLEEVE_MARKET_LABELS,
  TRADE_FLAG_LABELS,
  band,
  points,
} from "@/lib/policy";
import { formatSgtEt } from "@/lib/time";

const HREF = "/holdings/policy";
const cell = "px-3 py-1.5 text-right tabular-nums";
const head = "px-3 py-1.5 text-right font-normal text-neutral-400";
const left = "px-3 py-1.5 text-left font-normal text-neutral-400";

function Num({ termId, children, className = "" }: { termId: CompleteTermId; children: ReactNode; className?: string }) {
  return (
    <td className={`${cell} ${className}`}>
      <Metric termId={termId} icon={false}>
        {children}
      </Metric>
    </td>
  );
}

function driftTone(outside: boolean): string {
  return outside ? "text-amber-300" : "";
}

function Summary({ data }: { data: PolicyAssessment }) {
  const policy = data.policy;
  if (!policy) return null;
  const c = policy.content;
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2" aria-label="Policy in force">
      <div>
        <dt className="text-xs text-neutral-400">
          <Metric termId="investment_policy">Version in force</Metric>
        </dt>
        <dd>
          <Metric termId="investment_policy" icon={false}>
            {`Version ${policy.version}, saved ${formatSgtEt(policy.recorded_at)}`}
          </Metric>
          <span className="ml-2 text-neutral-400" data-quoted="">
            {policy.reason}
          </span>
        </dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-400">Horizon and limits</dt>
        <dd>
          <Metric termId="investment_policy" icon={false}>
            {[
              `${c.horizon_years} years`,
              c.max_drawdown_pct ? `largest drawdown ${Number(c.max_drawdown_pct)}%` : null,
              c.position_cap_pct ? `position cap ${Number(c.position_cap_pct)}%` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </Metric>
        </dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-400">Goals</dt>
        <dd data-quoted="">{c.goals}</dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-400">Risk</dt>
        <dd data-quoted="">{c.risk}</dd>
      </div>
    </dl>
  );
}

function Sleeves({ data }: { data: PolicyAssessment }) {
  const policy = data.policy;
  if (!policy || data.sleeves.length === 0) return null;
  const members = new Map(policy.content.sleeves.map((s) => [s.name, s.members]));
  const traded = data.sleeves.some((s) => s.after !== null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Sleeves">
        <thead>
          <tr className="border-b border-neutral-800">
            <th className={left}>
              <Metric termId="policy_sleeve">Sleeve</Metric>
            </th>
            <th className={head}>
              <Metric termId="target_weight">Target</Metric>
            </th>
            <th className={head}>
              <Metric termId="rebalancing_band">Band</Metric>
            </th>
            <th className={head}>
              <Metric termId="holding_weight">Actual</Metric>
            </th>
            <th className={head}>
              <Metric termId="policy_drift">Drift</Metric>
            </th>
            {traded ? (
              <th className={head}>
                <Metric termId="rebalancing_trade">After trades</Metric>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {data.sleeves.map((s) => (
            <tr key={s.name} data-sleeve={s.name} data-outside={s.outside} className="border-b border-neutral-900 align-top">
              <th scope="row" className="px-3 py-1.5 text-left font-normal">
                <span data-quoted="" className="font-medium">
                  {s.name}
                </span>
                <span className="ml-2 text-xs text-neutral-400">
                  {`${ASSET_CLASS_LABELS[s.asset_class] ?? s.asset_class} · ${SLEEVE_MARKET_LABELS[s.market] ?? s.market}`}
                </span>
                <span className="block text-xs text-neutral-500">
                  {(members.get(s.name) ?? []).map((m) => (
                    <span key={m.key} data-identifier="" className="mr-2">
                      {m.target_pct ? `${m.key} ${Number(m.target_pct)}%` : m.key}
                    </span>
                  ))}
                </span>
                {s.outside ? (
                  <span className="block text-xs text-amber-300">
                    <Metric termId="rebalancing_band" icon={false}>
                      outside its band
                    </Metric>
                  </span>
                ) : null}
              </th>
              <Num termId="target_weight">{weight(s.target)}</Num>
              <Num termId="rebalancing_band">{band(s.band)}</Num>
              <Num termId="holding_weight">{weight(s.actual)}</Num>
              <Num termId="policy_drift" className={driftTone(s.outside)}>
                {points(s.drift)}
              </Num>
              {traded ? <Num termId="rebalancing_trade">{weight(s.after)}</Num> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Groups({ title, rows, labels }: { title: string; rows: PolicyAssessment["markets"]; labels: Record<string, string> }) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label={title}>
        <thead>
          <tr className="border-b border-neutral-800">
            <th className={left}>{title}</th>
            <th className={head}>
              <Metric termId="target_weight">Target</Metric>
            </th>
            <th className={head}>
              <Metric termId="holding_weight">Actual</Metric>
            </th>
            <th className={head}>
              <Metric termId="policy_drift">Drift</Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => (
            <tr key={g.group} data-group={g.group} className="border-b border-neutral-900">
              <th scope="row" className="px-3 py-1.5 text-left font-normal">
                {labels[g.group] ?? g.group}
              </th>
              <Num termId="target_weight">{weight(g.target)}</Num>
              <Num termId="holding_weight">{weight(g.actual)}</Num>
              <Num termId="policy_drift">{points(g.drift)}</Num>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Holdings({ data }: { data: PolicyAssessment }) {
  if (data.holdings.length === 0) return <p className="text-sm text-neutral-400">Nothing held at this time.</p>;
  const policy = data.policy !== null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Holdings by sleeve">
        <thead>
          <tr className="border-b border-neutral-800">
            <th className={left}>Holding</th>
            {policy ? (
              <th className={left}>
                <Metric termId="policy_sleeve">Sleeve</Metric>
              </th>
            ) : null}
            <th className={head}>Value</th>
            <th className={head}>USD</th>
            <th className={head}>
              <Metric termId="holding_weight">Weight</Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.holdings.map((h) => (
            <tr key={h.key} data-holding={h.key} className="border-b border-neutral-900 align-top">
              <th scope="row" className="px-3 py-1.5 text-left font-normal">
                <span data-identifier="" className="font-medium">
                  {h.key}
                </span>
                {h.name ? (
                  <span className="ml-2 text-neutral-400">
                    <InstrumentName name={h.name} zh={h.name_zh ?? h.name} />
                  </span>
                ) : null}
                {h.over_cap || h.flags.length > 0 ? (
                  <span className="block text-xs text-amber-300">
                    {h.over_cap ? (
                      <Metric termId="position_cap" icon={false} className="mr-2">
                        above your position cap
                      </Metric>
                    ) : null}
                    {h.flags.map((flag) => (
                      <Metric key={flag} termId={FLAG_TERMS[flag] ?? "holding_flag"} icon={false} className="mr-2">
                        {FLAG_LABELS[flag] ?? flag}
                      </Metric>
                    ))}
                  </span>
                ) : null}
              </th>
              {policy ? (
                <td className="px-3 py-1.5 text-left">
                  {h.sleeve ? (
                    <span data-quoted="">{h.sleeve}</span>
                  ) : (
                    <Metric termId="policy_sleeve" icon={false} className="text-amber-300">
                      unassigned
                    </Metric>
                  )}
                </td>
              ) : null}
              <Num termId={h.market ? "price_mark" : "cash_balance"}>{formatMoney(h.value, h.currency)}</Num>
              <Num termId="fx_rate_used">{money(h.value_usd, "USD")}</Num>
              <Num termId="holding_weight">{weight(h.weight)}</Num>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Rebalancing({ data }: { data: PolicyAssessment }) {
  if (!data.policy) return null;
  const outside = data.sleeves.filter((s) => s.outside).length;
  let status: string;
  if (!data.due) status = "Every sleeve is within its band: no rebalancing is due.";
  else if (data.trades.length === 0)
    status = `${outside} ${outside === 1 ? "sleeve is" : "sleeves are"} outside ${outside === 1 ? "its band" : "their bands"}, but no trade is listed (see above).`;
  else
    status = `Rebalancing is due: ${outside} ${outside === 1 ? "sleeve is" : "sleeves are"} outside ${outside === 1 ? "its band" : "their bands"}. These trades would bring every sleeve to its target.`;
  return (
    <div className="space-y-3">
      <p className={data.due ? "text-amber-300" : "text-neutral-300"} data-due={data.due}>
        <Metric termId="rebalancing_due" icon={false}>
          {status}
        </Metric>
      </p>
      {data.trades.length > 0 ? (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Trades to the targets">
              <thead>
                <tr className="border-b border-neutral-800">
                  <th className={left}>Holding</th>
                  <th className={left}>
                    <Metric termId="policy_sleeve">Sleeve</Metric>
                  </th>
                  <th className={left}>
                    <Metric termId="rebalancing_trade">Trade</Metric>
                  </th>
                  <th className={head}>Shares</th>
                  <th className={head}>
                    <Metric termId="price_mark">Close</Metric>
                  </th>
                  <th className={head}>Amount</th>
                  <th className={head}>USD to target</th>
                  <th className={head}>
                    <Metric termId="target_weight">Weight now → target</Metric>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.trades.map((t) => (
                  <tr key={t.key} data-trade={t.key} data-side={t.side} className="border-b border-neutral-900 align-top">
                    <th scope="row" className="px-3 py-1.5 text-left font-normal">
                      <span data-identifier="" className="font-medium">
                        {t.key}
                      </span>
                      {t.name ? (
                        <span className="ml-2 text-neutral-400">
                          <InstrumentName name={t.name} zh={t.name_zh ?? t.name} />
                        </span>
                      ) : null}
                      {t.flags.length > 0 ? (
                        <span className="block text-xs text-amber-300">
                          {t.flags.map((flag) => (
                            <Metric key={flag} termId={flag === "no_close" ? "rebalancing_trade" : "price_mark"} icon={false} className="mr-2">
                              {TRADE_FLAG_LABELS[flag] ?? flag}
                            </Metric>
                          ))}
                        </span>
                      ) : null}
                    </th>
                    <td className="px-3 py-1.5 text-left">
                      <span data-quoted="">{t.sleeve}</span>
                    </td>
                    <td className="px-3 py-1.5 text-left">
                      <Metric termId="rebalancing_trade" icon={false}>
                        {SIDE_LABELS[t.side] ?? t.side}
                      </Metric>
                    </td>
                    <Num termId="rebalancing_trade">{t.shares !== null ? quantity(t.shares) : "n/a"}</Num>
                    <Num termId="price_mark">
                      {t.price !== null && t.mark ? `${formatMoney(t.price, t.currency)} (${t.mark.session})` : "n/a"}
                    </Num>
                    <Num termId="rebalancing_trade">{t.amount !== null ? formatMoney(t.amount, t.currency) : "n/a"}</Num>
                    <Num termId="rebalancing_trade">{money(t.amount_usd, "USD")}</Num>
                    <Num termId="target_weight">{`${weight(t.weight_before)} → ${weight(t.weight_target)}`}</Num>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.cash_flows.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="Cash moved by the trades">
                <thead>
                  <tr className="border-b border-neutral-800">
                    <th className={left}>
                      <Metric termId="policy_cash_flow">Currency</Metric>
                    </th>
                    <th className={head}>
                      <Metric termId="cash_balance">Cash now</Metric>
                    </th>
                    <th className={head}>
                      <Metric termId="policy_cash_flow">Sells less buys</Metric>
                    </th>
                    <th className={head}>After</th>
                  </tr>
                </thead>
                <tbody>
                  {data.cash_flows.map((f) => (
                    <tr key={f.currency} data-flow={f.currency} className="border-b border-neutral-900">
                      <th scope="row" className="px-3 py-1.5 text-left font-normal">
                        <span data-identifier="">{f.currency}</span>
                      </th>
                      <Num termId="cash_balance">{formatMoney(f.balance, f.currency)}</Num>
                      <Num termId="policy_cash_flow">{signedMoney(f.flow, f.currency)}</Num>
                      <Num termId="policy_cash_flow" className={Number(f.after) < 0 ? "text-rose-300" : ""}>
                        {Number(f.after) < 0
                          ? `${formatMoney(f.after, f.currency)}: a deposit or conversion first`
                          : formatMoney(f.after, f.currency)}
                      </Num>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="text-xs text-neutral-500">
            <Metric termId="rebalancing_trade" icon={false}>
              {`At the last closes known, TWD at the DEXTAUS rate${data.fx ? ` ${data.fx.value} for ${data.fx.observation_date}` : ""}, in whole shares rounded toward zero. Fees, taxes and board lots are not counted. Nothing here is sent to a broker; whether and how to trade is your decision.`}
            </Metric>
          </p>
        </>
      ) : null}
    </div>
  );
}

function Versions({ versions }: { versions: PolicyVersions | null }) {
  if (versions === null) {
    return (
      <p role="alert" className="text-sm text-neutral-400">
        Data unavailable: the versions could not be loaded.
      </p>
    );
  }
  if (versions.versions.length === 0) return <p className="text-sm text-neutral-400">No version saved yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Policy versions">
        <thead>
          <tr className="border-b border-neutral-800 text-left text-neutral-400">
            <th className="px-3 py-1.5 font-normal">
              <Metric termId="investment_policy">Version</Metric>
            </th>
            <th className="px-3 py-1.5 font-normal">Saved</th>
            <th className="px-3 py-1.5 font-normal">Sleeves</th>
            <th className="px-3 py-1.5 font-normal">Reason</th>
          </tr>
        </thead>
        <tbody>
          {versions.versions.map((v) => (
            <tr key={v.version} data-version={v.version} className="border-b border-neutral-900 align-top">
              <td className="px-3 py-1.5 tabular-nums">
                <Metric termId="investment_policy" icon={false}>
                  {String(v.version)}
                </Metric>
              </td>
              <td className="px-3 py-1.5 text-xs text-neutral-500">
                <Metric termId="investment_policy" icon={false}>
                  {formatSgtEt(v.recorded_at)}
                </Metric>
              </td>
              <td className="px-3 py-1.5">
                <Metric termId="target_weight" icon={false}>
                  {v.content.sleeves.map((s) => `${s.name} ${Number(s.target_pct)}%`).join(" · ")}
                </Metric>
              </td>
              <td className="px-3 py-1.5 text-neutral-400">
                <span data-quoted="">{v.reason}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The investment policy page (M3.12, ADR-043 IP13): Steven's own policy in force at the time shown
 * against his holdings, the drift by sleeve, asset class and market, and the trades that would
 * restore his targets. Arithmetic on his targets, not advice; local only. `form` is given when
 * viewing now (a version is saved at the system time).
 */
export function PolicyView({
  data,
  versions,
  knownOn,
  invalidKnownOn = false,
  form,
}: {
  data: PolicyAssessment;
  versions: PolicyVersions | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
  form?: ReactNode;
}) {
  return (
    <section className="space-y-6" data-page="policy">
      <header className="space-y-2">
        <p className="text-xs">
          <Link href="/holdings" className="text-neutral-400 underline-offset-2 hover:underline">
            ← Holdings
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_policy" zh>
            Investment Policy
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400" data-not-advice="">
          <Metric termId="page_policy" icon={false}>
            {data.detail}
          </Metric>
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-xs text-neutral-500">
          <Metric termId="investment_policy" icon={false}>
            {`Assessed at ${formatSgtEt(data.known_at)} as recorded by ${formatSgtEt(data.system_time)}, rebalancing ${data.rebalancing_version}`}
          </Metric>
        </p>
      </header>
      <Summary data={data} />
      {data.blocked.length > 0 ? (
        <ul className="space-y-1 text-sm text-amber-300" aria-label="Why no trade is listed">
          {data.blocked.map((reason) => (
            <li key={reason} data-blocked={reason}>
              <Metric termId={BLOCKED_TERMS[reason] ?? "investment_policy"} icon={false}>
                {BLOCKED_LABELS[reason] ?? reason}
              </Metric>
            </li>
          ))}
        </ul>
      ) : null}
      {data.policy ? (
        <section className="space-y-2" aria-labelledby="sleeves-title">
          <h2 id="sleeves-title" className="text-lg font-semibold">
            <Metric termId="policy_drift">Drift by sleeve</Metric>
          </h2>
          <Sleeves data={data} />
          <div className="grid gap-4 md:grid-cols-2">
            <Groups title="Asset class" rows={data.asset_classes} labels={ASSET_CLASS_LABELS} />
            <Groups title="Market" rows={data.markets} labels={SLEEVE_MARKET_LABELS} />
          </div>
        </section>
      ) : null}
      <section className="space-y-2" aria-labelledby="holdings-title">
        <h2 id="holdings-title" className="text-lg font-semibold">
          <Metric termId="holding_weight">Holdings</Metric>
        </h2>
        <Holdings data={data} />
      </section>
      {data.policy ? (
        <section className="space-y-2" aria-labelledby="rebalancing-title">
          <h2 id="rebalancing-title" className="text-lg font-semibold">
            <Metric termId="rebalancing_trade">Rebalancing</Metric>
          </h2>
          <Rebalancing data={data} />
        </section>
      ) : null}
      {form ? (
        <section className="space-y-2" aria-labelledby="write-title">
          <h2 id="write-title" className="text-lg font-semibold">
            <Metric termId="investment_policy">{data.policy ? "Write a new version" : "Write your policy"}</Metric>
          </h2>
          {form}
        </section>
      ) : null}
      <section className="space-y-2" aria-labelledby="versions-title">
        <h2 id="versions-title" className="text-lg font-semibold">
          <Metric termId="investment_policy">Versions</Metric>
        </h2>
        <Versions versions={versions} />
      </section>
    </section>
  );
}
