import Link from "next/link";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import type { EarningsDashboard, EarningsSummary, SourceHealth } from "@/lib/api";
import { TIMING_LABELS, formatDelta } from "@/lib/earnings";
import { formatChange } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

const HREF = "/dashboards/earnings";
const GUIDANCE_TEXT: Record<EarningsSummary["guidance_status"], string> = {
  extracted: "given",
  none: "none",
  not_read: "not read",
};

function instrumentHref(ticker: string, knownOn: string | undefined): string {
  return `/instruments/${ticker}${knownOn ? `?known_on=${knownOn}` : ""}#earnings`;
}

function Row({ row, knownOn }: { row: EarningsSummary; knownOn?: string }) {
  const cell = "px-2 py-2 text-right tabular-nums";
  return (
    <tr data-ticker={row.ticker} data-accession={row.accession} className="border-b border-neutral-900">
      <th scope="row" className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left font-normal">
        <Link href={instrumentHref(row.ticker, knownOn)} data-identifier="" className="font-medium underline-offset-2 hover:underline">
          {row.ticker}
        </Link>
        <span className="block max-w-[11rem] truncate text-xs text-neutral-500">{row.name}</span>
      </th>
      <td className="px-2 py-2 text-left">
        <Metric termId="earnings_event" icon={false}>
          <span className="whitespace-nowrap">{formatSgtEt(row.accepted_at)}</span>
        </Metric>
        <Metric termId="earnings_timing" icon={false} className="block text-xs text-neutral-500">
          {TIMING_LABELS[row.timing]}
        </Metric>
      </td>
      <td className={cell}>
        <Metric termId="earnings_report" icon={false}>
          {row.period_end ?? <span className="text-neutral-500">10-Q not yet public</span>}
        </Metric>
      </td>
      <td className={cell} data-column="revenue_yoy">
        <Metric termId="change_yoy" icon={false}>
          {row.revenue_yoy !== null ? formatChange(row.revenue_yoy) : <span className="text-neutral-500">n/a</span>}
        </Metric>
      </td>
      <td className={cell} data-column="eps_yoy">
        <Metric termId="change_yoy" icon={false}>
          {row.eps_yoy !== null ? formatChange(row.eps_yoy) : <span className="text-neutral-500">n/a</span>}
        </Metric>
      </td>
      <td className={cell} data-column="day0">
        <Metric termId="earnings_reaction" icon={false}>
          {row.day0_relative !== null ? (
            <span className={Number(row.day0_relative) >= 0 ? "text-emerald-300" : "text-rose-300"}>
              {formatDelta(row.day0_relative, "points")}
            </span>
          ) : (
            <span className="text-neutral-500">n/a</span>
          )}
        </Metric>
      </td>
      <td className="px-2 py-2 text-left" data-column="guidance">
        <Metric termId="guidance_statement" icon={false}>
          {GUIDANCE_TEXT[row.guidance_status]}
          {row.guidance_count ? ` (${row.guidance_count})` : ""}
        </Metric>
      </td>
      <td className="px-2 py-2 text-left">
        <Metric termId="consensus_estimate" icon={false} className="text-xs text-neutral-500">
          Data unavailable
        </Metric>
      </td>
    </tr>
  );
}

function Table({ rows, label, knownOn }: { rows: EarningsSummary[]; label: string; knownOn?: string }) {
  const head = "px-2 py-2 text-right align-bottom font-normal";
  return (
    <div className="overflow-x-auto rounded border border-neutral-800">
      <table className="w-full min-w-[56rem] text-sm" aria-label={label}>
        <thead>
          <tr className="border-b border-neutral-800 text-xs text-neutral-400">
            <th scope="col" className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left font-normal">
              Company
            </th>
            <th scope="col" className="px-2 py-2 text-left align-bottom font-normal">
              <Metric termId="earnings_event" icon={false}>
                Released
              </Metric>
            </th>
            <th scope="col" className={head}>
              <Metric termId="earnings_report" icon={false}>
                Quarter to
              </Metric>
            </th>
            <th scope="col" className={head}>
              <Metric termId="change_yoy" icon={false}>
                Revenue vs a year earlier
              </Metric>
            </th>
            <th scope="col" className={head}>
              <Metric termId="change_yoy" icon={false}>
                EPS vs a year earlier
              </Metric>
            </th>
            <th scope="col" className={head}>
              <Metric termId="earnings_reaction" icon={false}>
                Day 0 vs SPY
              </Metric>
            </th>
            <th scope="col" className="px-2 py-2 text-left align-bottom font-normal">
              <Metric termId="guidance_statement" icon={false}>
                Guidance
              </Metric>
            </th>
            <th scope="col" className="px-2 py-2 text-left align-bottom font-normal">
              <Metric termId="consensus_estimate" icon={false}>
                Consensus
              </Metric>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <Row key={row.accession} row={row} knownOn={knownOn} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Earnings dashboard (M1.5, ADR-026): each universe company's latest results release and every
 * release of the last two years, as known on the chosen date. Results are compared with the
 * company's own past; consensus has no provider (errata E6).
 */
export function EarningsDashboardView({
  data,
  sources,
  knownOn,
  invalidKnownOn = false,
}: {
  data: EarningsDashboard;
  sources: SourceHealth[] | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
}) {
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_earnings" zh>
            Earnings
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          Results releases at their EDGAR acceptance times, the quarter against a year earlier, and
          the market&apos;s reaction against SPY. There is no consensus provider, so no surprise is
          computed.
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing what was public by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(data.known_at)}
          </Metric>
        </p>
        <SourceFreshness sources={sources} ids={["sec_edgar", "alpaca_iex"]} />
      </header>
      <div className="space-y-2" data-block="latest">
        <h2 className="text-lg font-medium">
          <Metric termId="earnings_event">Latest release per company</Metric>
        </h2>
        {data.latest.length === 0 ? (
          <p className="text-sm text-neutral-400">No releases by this date.</p>
        ) : (
          <Table rows={data.latest} label="Latest releases" knownOn={knownOn} />
        )}
      </div>
      <div className="space-y-2" data-block="recent">
        <h2 className="text-lg font-medium">
          <Metric termId="earnings_event">Releases of the last two years</Metric>
        </h2>
        {data.recent.length === 0 ? (
          <p className="text-sm text-neutral-400">No releases in the last two years.</p>
        ) : (
          <Table rows={data.recent} label="Recent releases" knownOn={knownOn} />
        )}
      </div>
      <p className="text-xs text-neutral-500">
        Actuals appear once the <span data-identifier="">10-Q</span> or{" "}
        <span data-identifier="">10-K</span> is public; the reaction needs end-of-day closes, so a
        release after the close shows it from the next session. Open a company for the actuals,
        guidance quotes and filings.
      </p>
    </section>
  );
}
