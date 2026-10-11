import type { Metadata } from "next";

import { EarningsDashboardView } from "@/components/earnings/EarningsDashboardView";
import { Metric } from "@/components/Metric";
import { loadEarningsDashboard, loadSourceHealth } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// Point-in-time data: always read live, never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Earnings" };

export default async function EarningsPage({ searchParams }: PageProps<"/dashboards/earnings">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const [data, sources] = await Promise.all([loadEarningsDashboard(knownAt ?? undefined), loadSourceHealth()]);
  if (data === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_earnings">Earnings</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no earnings are shown.</p>
        </div>
      </section>
    );
  }
  return (
    <EarningsDashboardView
      data={data}
      sources={sources}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
    />
  );
}
