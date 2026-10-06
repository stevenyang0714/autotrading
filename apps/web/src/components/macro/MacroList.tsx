import Link from "next/link";

import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import type { MacroSeriesList, MacroSeriesSummary, SourceHealth } from "@/lib/api";
import { groupDigits } from "@/lib/format";
import { completeTermId } from "@/lib/glossary";
import { formatSgtEt } from "@/lib/time";

/** Macro index (M0.6): each registry series with its latest value. null = API unreachable. */
export function MacroList({
  data,
  sources,
}: {
  data: MacroSeriesList | null;
  sources?: SourceHealth[] | null;
}) {
  const newest = data?.series
    .map((s) => s.latest?.published_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_macro" zh>
            Macro
          </Metric>
        </h1>
        {sources !== undefined ? (
          <SourceFreshness sources={sources} ids={["fred"]} newestPublishedAt={newest} />
        ) : null}
        {data?.last_refresh_at ? (
          <p className="text-sm text-neutral-500">
            Last FRED refresh{" "}
            <Metric termId="as_of" icon={false}>
              {formatSgtEt(data.last_refresh_at)}
            </Metric>
          </p>
        ) : null}
      </header>
      {data === null ? (
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">
            The API could not be reached, so no macro series are shown.
          </p>
        </div>
      ) : data.series.length === 0 ? (
        <p className="text-sm text-neutral-500">
          No macro series yet. Run make migrate, then make fred-refresh.
        </p>
      ) : (
        <ul className="divide-y divide-neutral-800" aria-label="Macro series">
          {data.series.map((summary) => (
            <SeriesRow key={summary.series.id} summary={summary} />
          ))}
        </ul>
      )}
    </section>
  );
}

function SeriesRow({ summary }: { summary: MacroSeriesSummary }) {
  const { series, latest } = summary;
  const termId = completeTermId(series.term_id) ?? "page_macro";
  return (
    <li className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
      <Link
        href={`/macro/${series.id}`}
        className="min-w-0 break-words font-medium underline-offset-2 hover:underline md:min-w-[16rem]"
      >
        <Metric termId={termId} icon={false}>
          {series.title ?? series.id}
        </Metric>
      </Link>
      <span className="text-sm text-neutral-400" data-identifier="">
        {series.id}
      </span>
      {latest ? (
        <>
          <Metric termId={termId} icon={false}>
            <span className="tabular-nums">{groupDigits(latest.value)}</span>{" "}
            <span className="text-sm text-neutral-400">{series.units_short}</span>
          </Metric>
          <span className="text-sm text-neutral-400">
            for{" "}
            <Metric termId="observation_date" icon={false}>
              {latest.observation_date}
            </Metric>
            , released{" "}
            <Metric termId="vintage" icon={false}>
              {latest.vintage}
            </Metric>
          </span>
        </>
      ) : (
        <span className="text-sm text-neutral-500">No data yet</span>
      )}
    </li>
  );
}
