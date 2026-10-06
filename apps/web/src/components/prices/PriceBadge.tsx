import { Metric } from "@/components/Metric";
import type { FeedStatus } from "@/lib/api";

/** Badge text and tone per feed status (errata E4, glossary feed_status). */
export const FEED_STATUS: Record<FeedStatus, [label: string, tone: string]> = {
  live_consolidated: ["Live", "border-emerald-600/70 text-emerald-300"],
  live_single_venue: ["Live · IEX only", "border-sky-600/70 text-sky-300"],
  delayed: ["Delayed", "border-amber-600/70 text-amber-300"],
  end_of_day: ["Close", "border-neutral-600 text-neutral-300"],
  stale: ["Stale", "border-amber-600/70 text-amber-300"],
  unavailable: ["Data unavailable", "border-neutral-700 text-neutral-500"],
  fixture: ["Fixture", "border-fuchsia-600/70 text-fuchsia-300"],
  demo: ["Demo", "border-fuchsia-600/70 text-fuchsia-300"],
};

/** Text colour of a signed change (up green, down red, flat neutral). */
export function changeTone(value: string | null | undefined): string {
  const number = Number(value);
  if (!value || number === 0) return "text-neutral-400";
  return number > 0 ? "text-emerald-300" : "text-red-300";
}

/**
 * The feed status shown next to every price (errata E4): never let a single-venue, old or
 * recorded price pass for the live market.
 */
export function PriceBadge({ status, zh = false }: { status: FeedStatus; zh?: boolean }) {
  const [label, tone] = FEED_STATUS[status];
  return (
    <Metric termId="feed_status" icon={false} zh={zh}>
      <span
        data-feed-status={status}
        className={`inline-block rounded border px-1.5 py-0.5 text-[11px] leading-none whitespace-nowrap ${tone}`}
      >
        {label}
      </span>
    </Metric>
  );
}
