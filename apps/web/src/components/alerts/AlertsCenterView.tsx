import Link from "next/link";
import type { ReactNode } from "react";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import type { AlertEntry, Alerts, CompanyLevel, Convergence } from "@/lib/api";
import { FAMILY_NAMES, evidenceHref, levelClass, levelTerm } from "@/lib/alerts";
import { formatSgtEt } from "@/lib/time";

const HREF = "/dashboards/alerts-center";

export interface AlertFilters {
  status: "open" | "acknowledged" | "all";
  levelMin: number;
  ticker?: string;
  includeBackfilled: boolean;
}

/** A company alert's level, or a market-wide alert's own state: stress (M2.1), portfolio
 * drawdown (M2.3), a new S3 rotation target (M2.4) or a new S4 target (M3.0b). */
const MARKET_TERMS = {
  regime: "stress_state",
  portfolio: "portfolio_drawdown",
  rotation: "rotation_alert",
  momentum: "momentum_alert",
} as const;

function LevelBadge({ level, name, kind }: { level: number | null; name: string; kind?: AlertEntry["kind"] }) {
  const market =
    kind === "regime" || kind === "portfolio" || kind === "rotation" || kind === "momentum" ? MARKET_TERMS[kind] : null;
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-xs ${levelClass(level)}`}>
      <Metric termId={market ?? levelTerm(level)} icon={false}>
        {name}
      </Metric>
    </span>
  );
}

function Company({ company, knownOn }: { company: CompanyLevel; knownOn?: string }) {
  return (
    <li data-company={company.ticker} className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link
          href={`/instruments/${company.ticker}${knownOn ? `?known_on=${knownOn}` : ""}#buybacks`}
          data-identifier=""
          className="font-medium underline-offset-2 hover:underline"
        >
          {company.ticker}
        </Link>
        <LevelBadge level={company.level} name={company.level_name} />
      </div>
      <ul className="space-y-0.5 text-xs text-neutral-400" aria-label={`${company.ticker} level checks`}>
        {company.levels.map((check) => (
          <li key={check.level} data-check={check.level} data-status={check.status}>
            <Metric termId={levelTerm(check.level)} icon={false}>
              <span className={check.status === "pass" ? "text-emerald-300" : ""}>
                L{check.level} {check.status}
              </span>
              : {check.detail}
            </Metric>
          </li>
        ))}
      </ul>
      {company.items.length > 0 ? (
        <p className="text-xs text-neutral-500">
          <Metric termId="independent_evidence" icon={false}>
            {company.items.map((item) => item.label).join(" · ")} (
            {company.independent_families.map((f) => FAMILY_NAMES[f] ?? `family ${f}`).join(", ")})
          </Metric>
        </p>
      ) : null}
      <p className="text-xs text-neutral-500">
        <Metric termId="point_in_time" icon={false}>
          as of {formatSgtEt(company.known_at)}
          {company.backfilled ? " · backfilled" : ""}
        </Metric>
      </p>
    </li>
  );
}

function AlertItem({ alert, acknowledge }: { alert: AlertEntry; acknowledge?: ReactNode }) {
  return (
    <li
      data-alert={alert.id}
      data-kind={alert.kind}
      data-acknowledged={alert.acknowledgement ? "yes" : "no"}
      className="space-y-1 rounded border border-neutral-800 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <LevelBadge level={alert.level} name={alert.level_name} kind={alert.kind} />
        <Metric termId="alert" icon={false}>
          <span className="text-neutral-100">{alert.title}</span>
        </Metric>
      </div>
      <p className="text-xs text-neutral-500">
        <Metric termId="point_in_time" icon={false}>
          {formatSgtEt(alert.known_at)}
          {alert.backfilled ? " · backfilled" : ""}
        </Metric>
        {" · "}
        <Metric termId="alert_rule_set" icon={false}>
          alert rules {alert.rule_version}
        </Metric>
        {alert.delivered_at ? (
          <>
            {" · "}
            <span data-delivered="">
              <Metric termId="alert_delivery" icon={false}>
                sent to Telegram {formatSgtEt(alert.delivered_at)}
              </Metric>
            </span>
          </>
        ) : null}
      </p>
      <ul className="space-y-0.5 text-xs" aria-label="Evidence">
        {alert.evidence.map((evidence) => {
          const href = evidenceHref(evidence.table, evidence.url, alert.ticker, alert.known_at);
          const label = (
            <Metric termId="independent_evidence" icon={false}>
              {evidence.label}
            </Metric>
          );
          return (
            <li key={`${evidence.table}:${evidence.id}`} className="text-neutral-300">
              {href ? (
                <a
                  href={href}
                  {...(href.startsWith("http") ? { target: "_blank", rel: "noreferrer" } : {})}
                  className="underline-offset-2 hover:underline"
                >
                  {label}
                </a>
              ) : (
                label
              )}
            </li>
          );
        })}
      </ul>
      {alert.acknowledgement ? (
        <p className="text-xs text-emerald-300">
          <Metric termId="alert_acknowledgement" icon={false}>
            Acknowledged {formatSgtEt(alert.acknowledgement.acknowledged_at)}
            {alert.acknowledgement.note ? `: ${alert.acknowledgement.note}` : ""}
          </Metric>
        </p>
      ) : (
        acknowledge
      )}
    </li>
  );
}

function Filters({ filters, knownOn }: { filters: AlertFilters; knownOn?: string }) {
  const field = "rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700";
  return (
    <form method="get" action={HREF} aria-label="Filter alerts" className="flex flex-wrap items-center gap-2 text-sm">
      {knownOn ? <input type="hidden" name="known_on" value={knownOn} /> : null}
      <label className="flex items-center gap-1">
        <span>Status</span>
        <select name="status" defaultValue={filters.status} className={field}>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="all">All</option>
        </select>
      </label>
      <label className="flex items-center gap-1">
        <Metric termId="convergence_level" icon={false}>
          From level
        </Metric>
        <select name="level" defaultValue={String(filters.levelMin)} className={field}>
          <option value="0">Information</option>
          <option value="1">Watch</option>
          <option value="2">Thesis</option>
          <option value="3">Trade Candidate</option>
          <option value="4">Execution Ready</option>
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span>Company</span>
        <input
          name="ticker"
          defaultValue={filters.ticker ?? ""}
          maxLength={10}
          placeholder="All"
          className={`${field} w-20 uppercase`}
        />
      </label>
      <label className="flex items-center gap-1">
        <input type="checkbox" name="backfilled" value="1" defaultChecked={filters.includeBackfilled} />
        <span>Include backfilled</span>
      </label>
      <button
        type="submit"
        className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        Filter
      </button>
    </form>
  );
}

/**
 * Alerts Center (M1.7, ADR-028): each company's convergence level L0-L4 as known on the chosen
 * date and the alerts with their rule version, evidence and acknowledgement. In-app only.
 */
export function AlertsCenterView({
  alerts,
  convergence,
  filters,
  knownOn,
  invalidKnownOn = false,
  acknowledgeForm,
}: {
  alerts: Alerts;
  convergence: Convergence | null;
  filters: AlertFilters;
  knownOn?: string;
  invalidKnownOn?: boolean;
  /** The acknowledge form for an open alert, shown only when viewing now. */
  acknowledgeForm?: (alert: AlertEntry) => ReactNode;
}) {
  const open = Object.entries(alerts.open_by_level);
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_alerts_center" zh>
            Alerts Center
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          Where each company&apos;s signals line up, from information to a trade candidate, and the
          alerts the rules raised. Acknowledge an alert once you have looked at it.
        </p>
        <div role="note" data-in-app="" className="space-y-1 rounded border border-sky-700/60 bg-sky-950/30 px-3 py-2 text-sm text-sky-100">
          <p>
            <Metric termId="alert" icon={false}>
              {alerts.delivery?.configured ? "TELEGRAM ON" : "IN-APP ONLY"}
            </Metric>
            {" · "}
            <Metric termId="convergence_l4" icon={false}>
              {alerts.detail}
            </Metric>
          </p>
          {alerts.delivery ? (
            <p data-delivery={alerts.delivery.configured ? "on" : "off"} className="text-xs text-sky-200/80">
              <Metric termId="alert_delivery" icon={false}>
                {alerts.delivery.detail}
              </Metric>{" "}
              <Metric termId="delivery_rule_set" icon={false}>
                {alerts.delivery.rule_version ? `delivery rules ${alerts.delivery.rule_version}` : ""}
              </Metric>
            </p>
          ) : null}
        </div>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing what was known by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(alerts.known_at)}
          </Metric>{" "}
          under{" "}
          <Metric termId="alert_rule_set" icon={false}>
            alert rules {alerts.rule_version}
          </Metric>
        </p>
      </header>

      <div className="space-y-2" data-block="levels">
        <h2 className="text-lg font-medium">
          <Metric termId="convergence_level" zh>
            Convergence by company
          </Metric>
        </h2>
        {convergence === null ? (
          <p role="alert" className="text-sm text-neutral-400">
            Data unavailable: the levels could not be loaded.
          </p>
        ) : convergence.companies.length === 0 ? (
          <p className="text-sm text-neutral-400">No company was assessed by this date.</p>
        ) : (
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Convergence by company">
            {convergence.companies.map((company) => (
              <Company key={company.ticker} company={company} knownOn={knownOn} />
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-2" data-block="alerts">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-medium">
            <Metric termId="alert" zh>
              Alerts
            </Metric>
          </h2>
          <p className="text-xs text-neutral-400" data-open="">
            <Metric termId="alert" icon={false}>
              Open:{" "}
              {open.length === 0 ? "none" : open.map(([name, count]) => `${count} ${name}`).join(", ")}
            </Metric>
          </p>
        </div>
        <Filters filters={filters} knownOn={knownOn} />
        {alerts.entries.length === 0 ? (
          <p className="text-sm text-neutral-400">
            <Metric termId="alert" icon={false}>
              No alert matches these filters.
            </Metric>
          </p>
        ) : (
          <ol className="space-y-2" aria-label="Alerts">
            {alerts.entries.map((alert) => (
              <AlertItem key={alert.id} alert={alert} acknowledge={acknowledgeForm?.(alert)} />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
