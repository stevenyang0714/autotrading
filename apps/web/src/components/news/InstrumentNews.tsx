import Link from "next/link";

import { Metric } from "@/components/Metric";
import type { NewsFeed } from "@/lib/api";

import { NewsList } from "./NewsList";

function Column({ title, data, empty }: { title: string; data: NewsFeed | null; empty: string }) {
  return (
    <div className="min-w-0 space-y-1">
      <h3 className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium text-neutral-300">
        {title}
        {data ? (
          <span className="text-xs font-normal text-neutral-400">
            <Metric termId="story_count" icon={false}>
              {data.story_count} stories
            </Metric>
          </span>
        ) : null}
      </h3>
      {data === null ? (
        <p className="text-sm text-neutral-500">News unavailable: the API could not be reached.</p>
      ) : data.groups.length === 0 ? (
        <p className="text-sm text-neutral-500">{empty}</p>
      ) : (
        <NewsList groups={data.groups} compact />
      )}
    </div>
  );
}

/**
 * Recent news naming one company (M0.8, ADR-018), in two columns: the company's own
 * announcements (its newsroom feed) and coverage by media and government sources, so marketing
 * posts do not crowd out reporting.
 */
export function InstrumentNews({
  ticker,
  announcements,
  coverage,
}: {
  ticker: string;
  announcements: NewsFeed | null;
  coverage: NewsFeed | null;
}) {
  return (
    <section aria-label="Recent news" className="space-y-3">
      <h2 className="flex flex-wrap items-baseline gap-x-3 text-lg font-medium">
        <Metric termId="page_news" icon={false} zh>
          Recent news
        </Metric>
        <Link
          href={`/news?ticker=${encodeURIComponent(ticker)}`}
          className="text-xs font-normal text-neutral-400 underline-offset-2 hover:underline"
        >
          all <span data-identifier="">{ticker}</span> news
        </Link>
      </h2>
      <div className="grid gap-6 lg:grid-cols-2">
        <Column title="Media coverage" data={coverage} empty="No media coverage found for this company." />
        <Column
          title="Company announcements"
          data={announcements}
          empty="No announcement feed for this company (only some issuers publish one)."
        />
      </div>
    </section>
  );
}
