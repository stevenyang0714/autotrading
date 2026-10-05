import Link from "next/link";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import type { CompleteTermId } from "@/generated/glossary";
import type { MacroObservation, SeriesObservations, SourceHealth } from "@/lib/api";
import { groupDigits } from "@/lib/format";
import { completeTermId } from "@/lib/glossary";
import { formatSgtEt } from "@/lib/time";

interface Props {
  data: SeriesObservations;
  knownOn?: string;
  invalidKnownOn?: boolean;
  sources?: SourceHealth[] | null;
}

/**
 * One macro series (M0.6): the latest observations as known at `data.known_at` (ADR-012,
 * ADR-015). A revised value shows its first release. Every number renders through <Metric>.
 */
export function SeriesView({ data, knownOn, invalidKnownOn, sources }: Props) {
  const { series } = data;
  const termId = completeTermId(series.term_id) ?? "page_macro";
  return (
    <section className="space-y-8">
      <header className="space-y-3">
        <p className="text-sm">
          <Link href="/macro" className="text-neutral-400 hover:underline">
            <Metric termId="page_macro" icon={false}>
              Macro
            </Metric>
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">
          <Metric termId={termId} zh>
            {series.title ?? series.id}
          </Metric>
        </h1>
        {sources !== undefined ? (
          <SourceFreshness
            sources={sources}
            ids={["fred"]}
            newestPublishedAt={knownOn ? null : data.observations[0]?.published_at}
          />
        ) : null}
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
          <a
            href={`https://fred.stlouisfed.org/series/${series.id}`}
            target="_blank"
            rel="noreferrer"
            data-identifier=""
            className="underline-offset-2 hover:underline"
          >
            FRED {series.id}
          </a>
          {series.units ? (
            <Metric termId={termId} icon={false}>
              {series.units}
            </Metric>
          ) : null}
          {series.frequency ? <span>{series.frequency}</span> : null}
          {series.seasonal_adjustment_short ? (
            <span data-identifier="">{series.seasonal_adjustment_short}</span>
          ) : null}
        </p>
        <AsKnownOnForm
          href={`/macro/${encodeURIComponent(series.id)}`}
          knownOn={knownOn}
          invalid={invalidKnownOn}
        />
        <p className="text-sm text-neutral-400">
          Showing what was public by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(data.known_at)}
          </Metric>
          {data.last_refresh_at ? (
            <>
              {" · "}last FRED refresh{" "}
              <Metric termId="as_of" icon={false}>
                {formatSgtEt(data.last_refresh_at)}
              </Metric>
            </>
          ) : null}
        </p>
      </header>

      {data.observations.length === 0 ? (
        <p className="text-sm text-neutral-500">Nothing published as of this date.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm" aria-label="Observations">
            <thead className="text-xs text-neutral-400">
              <tr>
                <th className="py-2 pr-4 font-medium">
                  <Metric termId="observation_date">Period</Metric>
                </th>
                <th className="py-2 pr-4 font-medium">
                  <Metric termId={termId}>Value</Metric>
                </th>
                <th className="py-2 pr-4 font-medium">
                  <Metric termId="vintage">Released</Metric>
                </th>
                <th className="py-2 pr-4 font-medium">First release</th>
              </tr>
            </thead>
            <tbody>
              {data.observations.map((obs) => (
                <Row key={obs.observation_date} obs={obs} termId={termId} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Row({ obs, termId }: { obs: MacroObservation; termId: CompleteTermId }) {
  return (
    <tr className="border-t border-neutral-800 align-top" data-date={obs.observation_date}>
      <td className="whitespace-nowrap py-2 pr-4">
        <Metric termId="observation_date" icon={false}>
          {obs.observation_date}
        </Metric>
      </td>
      <td className="py-2 pr-4">
        <span className="flex flex-wrap items-center gap-2">
          <Metric termId={termId} icon={false}>
            <span className="tabular-nums">{groupDigits(obs.value)}</span>
          </Metric>
          {obs.revised ? (
            <Metric termId="vintage" icon={false}>
              <span className="rounded border border-amber-600/60 px-1.5 text-xs text-amber-300">
                Revised
              </span>
            </Metric>
          ) : null}
        </span>
      </td>
      <td className="whitespace-nowrap py-2 pr-4">
        <Metric termId="vintage" icon={false}>
          <span title={`Counted as public from ${formatSgtEt(obs.published_at)}`}>{obs.vintage}</span>
        </Metric>
      </td>
      <td className="py-2 pr-4 text-neutral-400">
        {obs.first_release ? (
          <Metric termId={termId} icon={false}>
            {groupDigits(obs.first_release.value)} on {obs.first_release.vintage}
          </Metric>
        ) : (
          <span>Same</span>
        )}
      </td>
    </tr>
  );
}
