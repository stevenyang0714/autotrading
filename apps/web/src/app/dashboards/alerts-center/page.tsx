import type { Metadata } from "next";

import { Metric } from "@/components/Metric";
import { AcknowledgeForm } from "@/components/alerts/AcknowledgeForm";
import { type AlertFilters, AlertsCenterView } from "@/components/alerts/AlertsCenterView";
import { loadAlerts, loadConvergence } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

import { acknowledgeAction } from "./actions";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Alerts Center" };

function text(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

export default async function AlertsCenterPage({ searchParams }: PageProps<"/dashboards/alerts-center">) {
  const query = await searchParams;
  const knownOn = text(query.known_on);
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const status = text(query.status);
  const level = Number(text(query.level) ?? "0");
  const filters: AlertFilters = {
    status: status === "acknowledged" || status === "all" ? status : "open",
    levelMin: Number.isInteger(level) && level >= 0 && level <= 3 ? level : 0,
    ticker: text(query.ticker)?.toUpperCase(),
    includeBackfilled: text(query.backfilled) === "1",
  };
  const [alerts, convergence] = await Promise.all([
    loadAlerts({ knownAt: knownAt ?? undefined, ...filters }),
    loadConvergence(knownAt ?? undefined),
  ]);
  if (alerts === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_alerts_center">Alerts Center</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no alerts are shown.</p>
        </div>
      </section>
    );
  }
  const params = new URLSearchParams(
    Object.entries({
      known_on: knownAt ? knownOn : undefined,
      status: filters.status === "open" ? undefined : filters.status,
      level: filters.levelMin ? String(filters.levelMin) : undefined,
      ticker: filters.ticker,
      backfilled: filters.includeBackfilled ? "1" : undefined,
    }).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
  const returnTo = `/dashboards/alerts-center${params.size ? `?${params.toString()}` : ""}`;
  return (
    <AlertsCenterView
      alerts={alerts}
      convergence={convergence}
      filters={filters}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      acknowledgeForm={
        knownAt ? undefined : (alert) => <AcknowledgeForm alertId={alert.id} returnTo={returnTo} action={acknowledgeAction} />
      }
    />
  );
}
