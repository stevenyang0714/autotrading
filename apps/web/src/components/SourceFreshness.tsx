import { Metric } from "@/components/Metric";
import { FRESHNESS, TONE_CLASS } from "@/components/data-health/labels";
import type { SourceHealth } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

interface Props {
  sources: SourceHealth[] | null;
  ids: string[];
  /** When the source published the newest value on this page (ISO), for its data age. */
  newestPublishedAt?: string | null;
  /** Reference time for the age (ISO); defaults to now. */
  now?: string;
}

/** "Days" or "hours" since `iso`, for the data age (glossary data_age). */
export function age(iso: string, now: string | undefined): string {
  const hours = Math.max(0, (new Date(now ?? Date.now()).getTime() - new Date(iso).getTime()) / 36e5);
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} days`;
}

/**
 * How current this page's data is (M0.6, ADR-016): per source, its freshness, our last
 * successful refresh, the next scheduled refresh, and how old the newest value shown is.
 */
export function SourceFreshness({ sources, ids, newestPublishedAt, now }: Props) {
  if (sources === null) {
    return (
      <p className="text-xs text-amber-400" role="status">
        Source status unavailable.
      </p>
    );
  }
  const shown = sources.filter((source) => ids.includes(source.id));
  return (
    <ul className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-neutral-400" aria-label="Data freshness">
      {shown.map((source) => {
        const [label, tone] = FRESHNESS[source.freshness ?? "disabled"];
        return (
          <li key={source.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span data-identifier="" className="font-medium text-neutral-300">
              {source.name.split(" (")[0]}
            </span>
            <Metric termId="data_freshness" icon={false} zh>
              <span className="inline-flex items-center gap-1">
                <span aria-hidden="true" className={`h-2 w-2 rounded-full ${TONE_CLASS[tone]}`} />
                {label}
              </span>
            </Metric>
            {source.last_success_at ? (
              <span>
                refreshed{" "}
                <Metric termId="as_of" icon={false}>
                  {formatSgtEt(source.last_success_at)}
                </Metric>
              </span>
            ) : null}
            {source.next_refresh_at ? (
              <span>
                next{" "}
                <Metric termId="next_refresh" icon={false}>
                  {formatSgtEt(source.next_refresh_at)}
                </Metric>
              </span>
            ) : null}
          </li>
        );
      })}
      {newestPublishedAt ? (
        <li>
          newest value published{" "}
          <Metric termId="data_age" icon={false} zh>
            {age(newestPublishedAt, now)} ago
          </Metric>
        </li>
      ) : null}
    </ul>
  );
}
