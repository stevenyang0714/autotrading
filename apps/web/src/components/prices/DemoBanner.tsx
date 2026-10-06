import { Metric } from "@/components/Metric";
import type { FeedStatus } from "@/lib/api";

/**
 * ADR-006: a DEMO DATA banner whenever recorded test data (fixture) or demo data feeds a
 * visible price. Renders nothing otherwise.
 */
export function DemoBanner({ statuses }: { statuses: (FeedStatus | null | undefined)[] }) {
  if (!statuses.some((status) => status === "fixture" || status === "demo")) return null;
  return (
    <div
      role="note"
      aria-label="Demo data"
      data-demo-banner=""
      className="rounded border border-fuchsia-600/70 bg-fuchsia-950/60 px-4 py-2 text-sm text-fuchsia-100"
    >
      <Metric termId="feed_status" icon={false}>
        <strong className="tracking-wide">DEMO DATA</strong>
      </Metric>{" "}
      Prices on this page are recorded test data, not the live market.
    </div>
  );
}
