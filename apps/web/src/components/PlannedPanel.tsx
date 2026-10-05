import { type DashboardDef, plannedLabel } from "@/lib/dashboards";

/** Placeholder for a dashboard that is not built yet. Shows no numbers other than the phase. */
export function PlannedPanel({ dashboard }: { dashboard: DashboardDef }) {
  return (
    <section aria-labelledby="dashboard-title" className="max-w-2xl space-y-4">
      <h1 id="dashboard-title" className="text-2xl font-semibold">
        {dashboard.label}
      </h1>
      <p className="text-neutral-600 dark:text-neutral-400">{dashboard.purpose}</p>
      <p
        data-testid="planned-phase"
        className="inline-block rounded border border-neutral-300 px-2 py-1 text-sm dark:border-neutral-700"
      >
        {plannedLabel(dashboard.plannedPhase)}
      </p>
      <p className="text-sm text-neutral-500">
        This dashboard is not built yet. It shows no data, live or simulated.
      </p>
    </section>
  );
}
