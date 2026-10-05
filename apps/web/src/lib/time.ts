/** Display helpers (ADR-005): timestamps are stored in UTC and shown in SGT with ET alongside. */

function parts(date: Date, timeZone: string): Record<string, string> {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  return Object.fromEntries(formatter.formatToParts(date).map((p) => [p.type, p.value]));
}

/** "2026-10-05 19:59 SGT · 10-05 07:59 ET" */
export function formatSgtEt(iso: string): string {
  const date = new Date(iso);
  const sg = parts(date, "Asia/Singapore");
  const ny = parts(date, "America/New_York");
  return `${sg.year}-${sg.month}-${sg.day} ${sg.hour}:${sg.minute} SGT · ${ny.month}-${ny.day} ${ny.hour}:${ny.minute} ET`;
}

/** Freshness SLA and similar durations: "2 days", "15 min". */
export function formatDuration(seconds: number): string {
  const units: [number, string][] = [
    [86400, "day"],
    [3600, "hour"],
    [60, "min"],
  ];
  for (const [size, name] of units) {
    if (seconds >= size && seconds % size === 0) {
      const count = seconds / size;
      return name === "min" ? `${count} min` : `${count} ${name}${count === 1 ? "" : "s"}`;
    }
  }
  return `${seconds} s`;
}
