import Link from "next/link";

import { InstrumentName } from "@/components/InstrumentName";
import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import { TwseAttribution } from "@/components/taiwan/TaiwanView";
import type { SourceHealth, TaiwanList as TaiwanListData } from "@/lib/api";
import { formatMoney, formatSigned } from "@/lib/format";
import { formatTaipei } from "@/lib/time";

/**
 * The Taiwan universe on the Instruments page (M3.7, ADR-039 TW13): each code's latest stored
 * TWSE session, the Taipei session state and the attribution. `data` null: the API is down.
 */
export function TaiwanList({ data, sources }: { data: TaiwanListData | null; sources?: SourceHealth[] | null }) {
  return (
    <section id="taiwan" className="space-y-3" data-block="taiwan" aria-labelledby="taiwan-title">
      <h2 id="taiwan-title" className="text-xl font-semibold">
        <Metric termId="taiwan_universe" zh>
          Taiwan (TWSE)
        </Metric>
      </h2>
      {sources !== undefined ? <SourceFreshness sources={sources} ids={["twse_openapi"]} /> : null}
      {data === null ? (
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no Taiwan instrument is shown.</p>
        </div>
      ) : (
        <>
          <p className="text-sm text-neutral-400">
            <Metric termId="taiwan_universe" icon={false}>
              The 10 largest listed companies by market cap on {data.ranked_on}, and {data.benchmark}, the
              benchmark
            </Metric>
            {" · "}
            <Metric termId="taiwan_market_session" icon={false}>
              {data.market_session.open ? "open now" : "closed"} · last close{" "}
              {formatTaipei(data.market_session.last_close)}
            </Metric>
            {data.missing_sessions.length > 0 ? (
              <>
                {" · "}
                <Metric termId="missed_session" icon={false} className="text-amber-300">
                  {data.missing_sessions.length} sessions missed
                </Metric>
              </>
            ) : null}
          </p>
          <ul className="divide-y divide-neutral-800" aria-label="Taiwan instruments">
            {data.rows.map((row) => (
              <li
                key={row.code}
                data-code={row.code}
                className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3"
              >
                <Link
                  href={`/instruments/${row.code}`}
                  data-identifier=""
                  className="w-16 font-medium underline-offset-2 hover:underline"
                >
                  {row.code}
                </Link>
                <span className="min-w-[12rem]">
                  <InstrumentName name={row.name} zh={row.name_zh} />
                </span>
                {row.close !== null ? (
                  <span className="tabular-nums text-sm">
                    <Metric termId="twse_close" icon={false}>
                      {formatMoney(row.close, "TWD")}
                    </Metric>
                    {row.change !== null ? (
                      <>
                        {" "}
                        <Metric termId="twse_price_change" icon={false} className="text-neutral-400">
                          {formatSigned(row.change)}
                        </Metric>
                      </>
                    ) : null}
                    {" · "}
                    <Metric termId="taiwan_market_session" icon={false} className="text-neutral-500">
                      {row.session}
                    </Metric>
                  </span>
                ) : (
                  <span className="text-sm text-neutral-500">No close stored by this date.</span>
                )}
              </li>
            ))}
          </ul>
          <p role="note" className="text-xs text-neutral-500">
            <Metric termId="taiwan_universe" icon={false}>
              {data.detail}
            </Metric>
          </p>
          <TwseAttribution attribution={data.attribution} />
        </>
      )}
    </section>
  );
}
