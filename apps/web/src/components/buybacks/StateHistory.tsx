import { Metric } from "@/components/Metric";
import type { StatePoint } from "@/lib/api";
import { STATE_LABELS, STATE_STYLES } from "@/lib/buybackStates";

/** One point per calendar month (New York): the latest stored state of that month. */
export function monthly(history: StatePoint[]): StatePoint[] {
  const byMonth = new Map<string, StatePoint>();
  for (const point of history) {
    const month = new Date(point.known_at).toLocaleDateString("en-CA", { timeZone: "America/New_York" }).slice(0, 7);
    byMonth.set(month, point);
  }
  return [...byMonth.values()];
}

function day(point: StatePoint): string {
  return new Date(point.known_at).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

/**
 * A company's buyback state over time (M1.4b): one square per month, coloured by state;
 * backfilled evaluations (computed after their date, B6) have a dashed border. The date and
 * state are in each square's label.
 */
export function StateHistory({ history, label }: { history: StatePoint[]; label: string }) {
  const points = monthly(history);
  return (
    <div className="space-y-1" data-block="state-history">
      <p className="text-xs text-neutral-400">
        <Metric termId="backfilled_evaluation" icon={false}>
          {label}: one square per month, dashed when backfilled
        </Metric>
      </p>
      <ol className="flex flex-wrap gap-0.5" aria-label={label}>
        {points.map((point) => {
          const text = `${day(point)}: ${STATE_LABELS[point.state]}${point.backfilled ? ", backfilled" : ""}`;
          return (
            <li
              key={point.known_at}
              title={text}
              aria-label={text}
              data-state={point.state}
              className={`h-3 w-3 rounded-sm border ${STATE_STYLES[point.state]} ${
                point.backfilled ? "border-dashed" : ""
              } ${point.state === "none" ? "bg-neutral-900" : ""}`}
            />
          );
        })}
      </ol>
    </div>
  );
}
