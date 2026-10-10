import Link from "next/link";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import { formatAnnounced } from "@/components/instruments/BuybacksView";
import type { BuybackStates, CompanyStates, SourceHealth, StateCondition, StatePoint } from "@/lib/api";
import {
  CONDITIONS,
  STATE_LABELS,
  STATE_STYLES,
  STATE_TERMS,
  STATUS_STYLES,
  conditionMeta,
  formatMeasure,
  formatThreshold,
} from "@/lib/buybackStates";
import { formatSgtEt } from "@/lib/time";

import { StatusText } from "./BuybackStateCard";
import { StateHistory } from "./StateHistory";

const HREF = "/dashboards/corporate-actions";
const KIND_LABELS = {
  new: "New authorization",
  increase: "Authorization increase",
  plan: "Buyback plan",
  remaining: "Remaining authorization",
} as const;
const TIMELINE = 8;

function instrumentHref(ticker: string, knownOn: string | undefined): string {
  return `/instruments/${ticker}${knownOn ? `?known_on=${knownOn}` : ""}#buybacks`;
}

function day(at: string): string {
  return new Date(at).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

/** The thresholds of the rule set, from any stored assignment (one rule version per page). */
function thresholds(companies: CompanyStates[]): Map<string, StateCondition> {
  const out = new Map<string, StateCondition>();
  for (const company of companies) {
    for (const condition of company.assignment?.assessment.conditions ?? []) {
      if (!out.has(condition.condition_id)) out.set(condition.condition_id, condition);
    }
  }
  return out;
}

function ReviewCell({ condition }: { condition: StateCondition | undefined }) {
  if (!condition) return <td className="px-2 py-2 text-right text-neutral-600">—</td>;
  const meta = conditionMeta(condition.condition_id);
  return (
    <td
      className="px-2 py-2 text-right tabular-nums"
      data-condition={condition.condition_id}
      data-status={condition.status}
      title={condition.detail}
    >
      <Metric termId={meta.termId} icon={false}>
        <span className={STATUS_STYLES[condition.status]}>
          {condition.value !== null ? formatMeasure(condition.value, condition.unit) : condition.status}
        </span>
      </Metric>
    </td>
  );
}

/** Announcements and state changes of one company, newest first. */
function timeline(company: CompanyStates): { day: string; text: string; kind: "announcement" | "state" }[] {
  const changes: { day: string; text: string; kind: "state" }[] = [];
  let previous: StatePoint | null = null;
  for (const point of company.history) {
    if (previous === null || previous.state !== point.state) {
      changes.push({
        day: day(point.known_at),
        text: `State ${STATE_LABELS[point.state]}${point.backfilled ? " (backfilled)" : ""}`,
        kind: "state",
      });
    }
    previous = point;
  }
  const announced = company.announcements.map((event) => ({
    day: event.day,
    text: `${KIND_LABELS[event.kind]} ${formatAnnounced(event.amount)}`,
    kind: "announcement" as const,
  }));
  return [...announced, ...changes].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
}

function CompanyHistory({ company, knownOn }: { company: CompanyStates; knownOn?: string }) {
  const entries = timeline(company);
  return (
    <li className="space-y-2 rounded border border-neutral-800 p-3" data-company={company.ticker}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <Link href={instrumentHref(company.ticker, knownOn)} data-identifier="" className="font-medium underline-offset-2 hover:underline">
          {company.ticker}
        </Link>
        <span className="text-xs text-neutral-500">{company.name}</span>
      </div>
      {company.history.length > 0 ? (
        <StateHistory history={company.history} label={`${company.ticker} state history`} />
      ) : (
        <p className="text-xs text-neutral-500">No stored states by this date.</p>
      )}
      {entries.length > 0 ? (
        <details className="text-xs" open={entries.length <= 3}>
          <summary className="cursor-pointer select-none text-neutral-400">
            <Metric termId="buyback_record" icon={false}>
              Timeline: {Math.min(entries.length, TIMELINE)} latest of {entries.length}
            </Metric>
          </summary>
          <ol className="mt-1 space-y-0.5" aria-label={`${company.ticker} timeline`}>
            {entries.slice(0, TIMELINE).map((entry) => (
              <li key={`${entry.kind}-${entry.day}-${entry.text}`} data-entry={entry.kind}>
                <Metric termId={entry.kind === "announcement" ? "repurchase_announcement" : "buyback_state"} icon={false}>
                  <span className="tabular-nums text-neutral-500">{entry.day}</span>{" "}
                  <span className="text-neutral-200">{entry.text}</span>
                </Metric>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </li>
  );
}

/**
 * Corporate Actions dashboard (M1.4b, ADR-025): the threshold review (every universe company's
 * buyback state under the active rule version, each condition against its threshold, the
 * score), then each company's state history and buyback timeline, as known on the chosen date.
 */
export function CorporateActionsView({
  data,
  sources,
  knownOn,
  invalidKnownOn = false,
}: {
  data: BuybackStates;
  sources: SourceHealth[] | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
}) {
  const rule = data.rule_set;
  const columns = thresholds(data.companies);
  const ids = Object.keys(CONDITIONS);
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_corporate_actions" zh>
            Corporate Actions
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          Buyback states: what boards announced, what companies actually repurchased, and whether
          it was affordable and well timed. A state is a research label; none triggers a trade.
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing the states stored by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(data.known_at)}
          </Metric>
          , under{" "}
          <Metric termId="buyback_rule_version" icon={false}>
            rule v{rule.rule_version} (approved {rule.approved})
          </Metric>
          .
        </p>
        <SourceFreshness sources={sources} ids={["sec_edgar", "alpaca_iex"]} />
      </header>

      <div className="space-y-2" data-block="threshold-review">
        <h2 className="text-lg font-medium">
          <Metric termId="threshold_review" zh>
            Threshold review
          </Metric>
        </h2>
        <p className="text-xs text-amber-300">
          <Metric termId="buyback_rule_version" icon={false}>
            Thresholds are defaults, not validated. A change is a new rule version.
          </Metric>
        </p>
        <div className="overflow-x-auto rounded border border-neutral-800">
          <table className="w-full min-w-[72rem] text-sm" aria-label="Threshold review">
            <thead>
              <tr className="border-b border-neutral-800 text-xs text-neutral-400">
                <th scope="col" className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left font-normal">
                  Company
                </th>
                <th scope="col" className="px-2 py-2 text-left font-normal">
                  <Metric termId="buyback_state" icon={false}>
                    State
                  </Metric>
                </th>
                <th scope="col" className="px-2 py-2 text-right font-normal">
                  <Metric termId="buyback_quality_score" icon={false}>
                    Score
                  </Metric>
                </th>
                {ids.map((id) => {
                  const meta = conditionMeta(id);
                  const found = columns.get(id);
                  return (
                    <th key={id} scope="col" className="px-2 py-2 text-right align-bottom font-normal" data-column={id}>
                      <Metric termId={meta.termId} icon={false}>
                        <span className="block">{meta.short}</span>
                        {found ? <span className="block text-neutral-500">{formatThreshold(found)}</span> : null}
                      </Metric>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {data.companies.map((company) => {
                const assessment = company.assignment?.assessment;
                const byId = new Map(assessment?.conditions.map((c) => [c.condition_id, c]) ?? []);
                return (
                  <tr key={company.ticker} data-ticker={company.ticker} className="border-b border-neutral-900">
                    <th scope="row" className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left font-normal">
                      <Link
                        href={instrumentHref(company.ticker, knownOn)}
                        data-identifier=""
                        className="font-medium underline-offset-2 hover:underline"
                      >
                        {company.ticker}
                      </Link>
                      <span className="block max-w-[11rem] truncate text-xs text-neutral-500">{company.name}</span>
                    </th>
                    <td className="px-2 py-2">
                      {assessment ? (
                        <Metric termId={STATE_TERMS[assessment.state]} icon={false}>
                          <span
                            className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-semibold ${STATE_STYLES[assessment.state]}`}
                            data-state={assessment.state}
                          >
                            {STATE_LABELS[assessment.state]}
                          </span>
                        </Metric>
                      ) : (
                        <span className="text-xs text-neutral-500">not evaluated</span>
                      )}
                      {company.assignment?.backfilled ? (
                        <Metric termId="backfilled_evaluation" icon={false} className="ml-1 text-xs text-neutral-500">
                          backfilled
                        </Metric>
                      ) : null}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums" data-column="score">
                      <Metric termId="buyback_quality_score" icon={false}>
                        {assessment?.score.total ?? <span className="text-neutral-500">n/a</span>}
                      </Metric>
                    </td>
                    {ids.map((id) => (
                      <ReviewCell key={id} condition={byId.get(id)} />
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-neutral-500">
          Colours:{" "}
          <span className={STATUS_STYLES.pass}>pass</span>,{" "}
          <span className={STATUS_STYLES.fail}>fail</span>,{" "}
          <span className={STATUS_STYLES.unavailable}>unavailable</span> (
          <Metric termId="condition_status" icon={false}>
            missing data never passes
          </Metric>
          ). Hover a value for its detail; open a company for every input and filing. The score is
          unavailable when any component is.
        </p>
        <Details companies={data.companies} />
      </div>

      <div className="space-y-2" data-block="history">
        <h2 className="text-lg font-medium">
          <Metric termId="buyback_state">State history and timeline</Metric>
        </h2>
        <ul className="grid gap-3 md:grid-cols-2">
          {data.companies.map((company) => (
            <CompanyHistory key={company.ticker} company={company} knownOn={knownOn} />
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Each company's levels and unavailable reasons, for the review. */
function Details({ companies }: { companies: CompanyStates[] }) {
  const rows = companies.filter((c) => c.assignment);
  if (rows.length === 0) return null;
  return (
    <details className="text-xs text-neutral-400" data-review-details="">
      <summary className="cursor-pointer select-none">Levels and reasons per company</summary>
      <ul className="mt-1 space-y-2">
        {rows.map((company) => (
          <li key={company.ticker}>
            <span data-identifier="" className="font-medium text-neutral-200">
              {company.ticker}
            </span>
            <ul className="ml-3">
              {company.assignment?.assessment.levels.map((level) => (
                <li key={level.level}>
                  <Metric termId={STATE_TERMS[level.level]} icon={false}>
                    {STATE_LABELS[level.level]}
                  </Metric>{" "}
                  <StatusText status={level.status} />
                  {level.status !== "pass" ? (
                    <ul className="ml-3">
                      {company.assignment?.assessment.conditions
                        .filter((c) => c.level === level.level && c.status !== "pass")
                        .map((c) => (
                          <li key={c.condition_id}>
                            <Metric termId={conditionMeta(c.condition_id).termId} icon={false}>
                              {conditionMeta(c.condition_id).label}: {c.detail}
                            </Metric>
                          </li>
                        ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </details>
  );
}
