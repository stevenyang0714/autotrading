import Link from "next/link";

import { Metric } from "@/components/Metric";
import { DemoBanner } from "@/components/prices/DemoBanner";
import { SourceFreshness } from "@/components/SourceFreshness";
import { FRESHNESS } from "@/components/data-health/labels";
import type { NewsFeed, NewsKind, SourceHealth } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

import { NewsList } from "./NewsList";

export interface NewsSelection {
  ticker?: string;
  source?: string;
  maxTier?: number;
  kind?: NewsKind;
  knownOn?: string;
  invalidKnownOn?: boolean;
}

export const KIND_CHOICES: [NewsKind | "", string][] = [
  ["", "All types"],
  ["official", "Official releases"],
  ["press_release", "Company announcements"],
  ["article", "Media coverage"],
];

const TIER_CHOICES: [string, string][] = [
  ["", "All tiers"],
  ["1", "Tier 1: official and issuers"],
  ["2", "Tiers 1-2: plus professional media"],
  ["3", "Tiers 1-3: plus specialist"],
];

/**
 * News page (M0.8 minimal, ADR-018). One GET form for every filter, so the page works without
 * client JavaScript and the selection stays in the URL.
 */
export function NewsView({
  data,
  sources,
  tickers,
  selection,
}: {
  data: NewsFeed | null;
  sources: SourceHealth[] | null;
  tickers: string[];
  selection: NewsSelection;
}) {
  const fixture = data?.groups.some((g) => [g.lead, ...g.others].some((i) => i.data_mode === "fixture"));
  const feedIds = new Set((data?.sources ?? []).map((s) => s.id).filter((id) => id !== "gdelt"));
  const feedStates = (sources ?? []).filter((s) => feedIds.has(s.id)).map((s) => FRESHNESS[s.freshness ?? "disabled"][0]);
  const feedSummary = Object.entries(
    feedStates.reduce<Record<string, number>>((acc, label) => ({ ...acc, [label]: (acc[label] ?? 0) + 1 }), {}),
  );
  return (
    <section className="space-y-6">
      <DemoBanner statuses={fixture ? ["fixture"] : []} />
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_news" zh>
            News
          </Metric>
        </h1>
        <form method="get" action="/news" className="flex flex-wrap items-center gap-2 text-sm" aria-label="News filters">
          <select name="ticker" defaultValue={selection.ticker ?? ""} aria-label="Company" className="rounded border border-neutral-700 bg-transparent px-2 py-1">
            <option value="">All companies</option>
            {tickers.map((ticker) => (
              <option key={ticker} value={ticker}>
                {ticker}
              </option>
            ))}
          </select>
          <span data-identifier="">
            <select name="source" defaultValue={selection.source ?? ""} aria-label="Source" className="rounded border border-neutral-700 bg-transparent px-2 py-1">
              <option value="">All sources</option>
              {(data?.sources ?? []).map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>
          </span>
          <select name="kind" defaultValue={selection.kind ?? ""} aria-label="Type" className="rounded border border-neutral-700 bg-transparent px-2 py-1">
            {KIND_CHOICES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <Metric termId="source_tier" icon={false}>
            <select name="tier" defaultValue={selection.maxTier ? String(selection.maxTier) : ""} aria-label="Tier" className="rounded border border-neutral-700 bg-transparent px-2 py-1">
              {TIER_CHOICES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Metric>
          <label htmlFor="known_on">
            <Metric termId="point_in_time">As known on</Metric>
          </label>
          <input
            id="known_on"
            name="known_on"
            type="date"
            defaultValue={selection.invalidKnownOn ? "" : (selection.knownOn ?? "")}
            className="rounded border border-neutral-700 bg-transparent px-2 py-1"
          />
          <button type="submit" className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800">
            Show
          </button>
          <Link href="/news" className="text-neutral-400 underline-offset-2 hover:underline">
            Reset
          </Link>
          {selection.invalidKnownOn ? (
            <span role="status" className="text-amber-400">
              Not a calendar date; showing today.
            </span>
          ) : null}
        </form>
        {data ? (
          <p className="text-sm text-neutral-400">
            Showing what was public by{" "}
            <Metric termId="point_in_time" icon={false}>
              {formatSgtEt(data.known_at)}
            </Metric>
            {" · "}
            <Metric termId="story_count" zh>
              {data.story_count} stories
            </Metric>{" "}
            from{" "}
            <Metric termId="duplicate_group" icon={false}>
              {data.article_count} articles
            </Metric>
          </p>
        ) : null}
        <SourceFreshness
          sources={sources}
          ids={["gdelt"]}
          newestPublishedAt={selection.knownOn ? null : (data?.newest_published_at ?? null)}
        />
        {feedSummary.length ? (
          <p className="text-xs text-neutral-400">
            Official feeds:{" "}
            {feedSummary.map(([label, count], i) => (
              <span key={label}>
                {i ? ", " : ""}
                <Metric termId="data_freshness" icon={false}>
                  {count} {label}
                </Metric>
              </span>
            ))}{" "}
            (<Link href="/system/data-health" className="underline-offset-2 hover:underline">Data Health</Link>)
          </p>
        ) : null}
      </header>
      {data === null ? (
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no news is shown.</p>
        </div>
      ) : (
        <NewsList groups={data.groups} />
      )}
      {data ? (
        <p className="text-xs text-neutral-500">
          <a href={data.attribution_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
            {data.attribution}
          </a>
          . Headlines and summaries are the publishers&rsquo; own; only titles, links, times and short
          summaries are stored, never article text.
        </p>
      ) : null}
    </section>
  );
}
