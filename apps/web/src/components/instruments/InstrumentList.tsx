import Link from "next/link";

import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import type { InstrumentList as InstrumentListData, SourceHealth } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

/** Instruments index (M0.5b). `data` is null when the API is unreachable. */
export function InstrumentList({
  data,
  sources,
}: {
  data: InstrumentListData | null;
  sources?: SourceHealth[] | null;
}) {
  const newest = data?.instruments
    .map((i) => i.latest_report?.published_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_instruments" zh>
            Instruments
          </Metric>
        </h1>
        {sources !== undefined ? (
          <SourceFreshness sources={sources} ids={["sec_edgar"]} newestPublishedAt={newest} />
        ) : null}
        {data?.last_refresh_at ? (
          <p className="text-sm text-neutral-500">
            Last SEC refresh{" "}
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
            The API could not be reached, so no instruments are shown.
          </p>
        </div>
      ) : data.instruments.length === 0 ? (
        <p className="text-sm text-neutral-500">
          No instruments yet. They appear after the first SEC refresh (make sec-refresh).
        </p>
      ) : (
        <ul className="divide-y divide-neutral-800" aria-label="Instruments">
          {data.instruments.map((instrument) => (
            <li key={instrument.ticker} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
              <Link
                href={`/instruments/${instrument.ticker}`}
                data-identifier=""
                className="w-16 font-medium underline-offset-2 hover:underline"
              >
                {instrument.ticker}
              </Link>
              <span className="min-w-[12rem]">{instrument.name}</span>
              <span className="text-sm text-neutral-400" data-identifier="">
                {[instrument.exchange, instrument.cik ? `CIK ${instrument.cik}` : null]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {instrument.latest_report ? (
                <span className="text-sm text-neutral-400">
                  Latest report{" "}
                  <a
                    href={instrument.latest_report.url}
                    target="_blank"
                    rel="noreferrer"
                    data-identifier=""
                    className="underline-offset-2 hover:underline"
                  >
                    {instrument.latest_report.form}
                  </a>{" "}
                  <Metric termId="filing_date" icon={false}>
                    {formatSgtEt(instrument.latest_report.published_at)}
                  </Metric>
                </span>
              ) : null}
              {instrument.predecessors.length > 0 ? (
                <span className="text-sm text-neutral-400">
                  history incl.{" "}
                  <Metric termId="predecessor_issuer" icon={false}>
                    {instrument.predecessors.join(", ")}
                  </Metric>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
