import { Metric } from "@/components/Metric";
import type { NewsGroup, NewsItem } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

const TIER_TONE: Record<number, string> = {
  1: "border-emerald-600/70 text-emerald-300",
  2: "border-sky-600/70 text-sky-300",
  3: "border-neutral-600 text-neutral-300",
  4: "border-amber-600/70 text-amber-300",
};

export function TierBadge({ tier }: { tier: number }) {
  return (
    <Metric termId="source_tier" icon={false}>
      <span
        data-tier={tier}
        className={`inline-block rounded border px-1.5 py-0.5 text-[11px] leading-none whitespace-nowrap ${TIER_TONE[tier] ?? TIER_TONE[4]}`}
      >
        Tier {tier}
      </span>
    </Metric>
  );
}

function When({ item }: { item: NewsItem }) {
  return (
    <Metric termId="news_time_basis" icon={false}>
      {formatSgtEt(item.published_at)}
      {item.time_basis === "first_seen" ? " (first seen)" : ""}
    </Metric>
  );
}

/**
 * News stories (M0.8, ADR-018): one row per duplicate group, its lead headline linking to the
 * original article, the other copies behind a disclosure. Headlines and summaries are the
 * publisher's own words, shown verbatim ([data-quoted]); every number of ours is a <Metric>.
 */
export function NewsList({ groups, compact = false }: { groups: NewsGroup[]; compact?: boolean }) {
  if (groups.length === 0) {
    return <p className="text-sm text-neutral-500">No news stories for this selection.</p>;
  }
  return (
    <ul className="divide-y divide-neutral-800" aria-label="News stories">
      {groups.map((group) => (
        <Story key={group.group_id} group={group} compact={compact} />
      ))}
    </ul>
  );
}

function Story({ group, compact }: { group: NewsGroup; compact: boolean }) {
  const lead = group.lead;
  return (
    <li className="space-y-1 py-3" data-group={group.group_id} data-articles={group.article_count}>
      <p className="flex items-start gap-2">
        <TierBadge tier={group.best_tier} />
        <a
          href={lead.url}
          target="_blank"
          rel="noreferrer"
          data-quoted=""
          className="font-medium underline-offset-2 hover:underline"
        >
          {lead.title}
        </a>
      </p>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-400">
        <span data-identifier="">{lead.publisher}</span>
        <When item={lead} />
        {group.tickers.map((ticker) => (
          <a
            key={ticker}
            href={`/instruments/${ticker}`}
            data-identifier=""
            className="rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-200 hover:bg-neutral-700"
          >
            {ticker}
          </a>
        ))}
        {group.article_count > 1 ? (
          <Metric termId="duplicate_group" icon={false}>
            {group.article_count} copies on {group.publisher_count} sites
          </Metric>
        ) : null}
      </p>
      {lead.snippet && !compact ? (
        <p className="text-sm text-neutral-300" data-quoted="">
          {lead.snippet}
        </p>
      ) : null}
      {group.others.length > 0 && !compact ? (
        <details className="text-xs text-neutral-400">
          <summary className="cursor-pointer select-none">Other copies</summary>
          <ul className="mt-1 space-y-1 pl-4">
            {group.others.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-x-2">
                <TierBadge tier={item.source_tier} />
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  data-identifier=""
                  className="underline-offset-2 hover:underline"
                >
                  {item.publisher}
                </a>
                <When item={item} />
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </li>
  );
}
