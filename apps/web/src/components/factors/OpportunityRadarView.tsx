import Link from "next/link";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { DemoBanner } from "@/components/prices/DemoBanner";
import type { FactorRow, FactorsTable, FeedStatus } from "@/lib/api";
import {
  FUNDAMENTAL_COLUMNS,
  TREND_COLUMNS,
  type SortDir,
  formatMeasure,
  meta,
  ordinal,
  rowValue,
  sortRows,
} from "@/lib/factors";
import { formatSgtEt } from "@/lib/time";

const HREF = "/dashboards/opportunity-radar";

function sortHref(knownOn: string | undefined, key: string, dir: SortDir): string {
  const query = new URLSearchParams({ ...(knownOn ? { known_on: knownOn } : {}), sort: key, dir });
  return `${HREF}?${query.toString()}`;
}

function instrumentHref(ticker: string, knownOn: string | undefined): string {
  return `/instruments/${ticker}${knownOn ? `?known_on=${knownOn}` : ""}#factors`;
}

function HeaderLink({
  label,
  columnKey,
  sort,
  dir,
  knownOn,
  children,
}: {
  label: string;
  columnKey: string;
  sort: string;
  dir: SortDir;
  knownOn?: string;
  children: React.ReactNode;
}) {
  const active = sort === columnKey;
  const next: SortDir = active ? (dir === "asc" ? "desc" : "asc") : columnKey === "ticker" ? "asc" : "desc";
  return (
    <Link
      href={sortHref(knownOn, columnKey, next)}
      aria-label={`Sort by ${label}`}
      className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
    >
      {children}
      {active ? <span aria-hidden="true">{dir === "asc" ? "▲" : "▼"}</span> : null}
    </Link>
  );
}

function Ticker({ row, knownOn }: { row: FactorRow; knownOn?: string }) {
  return (
    <th scope="row" className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left font-normal">
      <Link
        href={instrumentHref(row.ticker, knownOn)}
        data-identifier=""
        className="font-medium underline-offset-2 hover:underline"
      >
        {row.ticker}
      </Link>
      <span className="block text-xs text-neutral-500">
        {row.instrument_type === "etf" ? "ETF" : "Equity"}
        {row.price?.last_close ? (
          <>
            {" · "}
            <Metric termId="point_in_time" icon={false}>
              close {row.price.last_close}
            </Metric>
          </>
        ) : null}
      </span>
    </th>
  );
}

function Header({
  columns,
  sort,
  dir,
  knownOn,
}: {
  columns: readonly string[];
  sort: string;
  dir: SortDir;
  knownOn?: string;
}) {
  return (
    <thead>
      <tr className="border-b border-neutral-800 text-xs text-neutral-400">
        <th
          scope="col"
          aria-sort={sort === "ticker" ? (dir === "asc" ? "ascending" : "descending") : undefined}
          className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left font-normal"
        >
          <HeaderLink label="ticker" columnKey="ticker" sort={sort} dir={dir} knownOn={knownOn}>
            Instrument
          </HeaderLink>
        </th>
        {columns.map((key) => {
          const info = meta(key);
          return (
            <th
              key={key}
              scope="col"
              aria-sort={sort === key ? (dir === "asc" ? "ascending" : "descending") : undefined}
              className="px-3 py-2 text-right align-bottom font-normal"
            >
              <HeaderLink label={info.label} columnKey={key} sort={sort} dir={dir} knownOn={knownOn}>
                <Metric termId={info.termId} icon={false}>
                  {info.short}
                </Metric>
              </HeaderLink>
            </th>
          );
        })}
      </tr>
    </thead>
  );
}

function TrendCell({ row, measureId }: { row: FactorRow; measureId: string }) {
  const found = rowValue(row, measureId);
  const info = meta(measureId);
  return (
    <td data-column={measureId} className="px-3 py-2 text-right tabular-nums">
      <Metric termId={info.termId} icon={false}>
        {found && found.value !== null ? (
          <>
            {formatMeasure(found.value, found.unit, found.group)}
            {found.notes > 0 ? (
              <sup className="text-amber-300" title="a dividend may be missing in its window">
                *
              </sup>
            ) : null}
          </>
        ) : (
          <span className="text-neutral-500">{found?.reason === "not_meaningful" ? "n/m" : "n/a"}</span>
        )}
      </Metric>
      {found && found.percentile !== null && found.value !== null ? (
        <span className="block text-xs text-neutral-500">
          <Metric termId="factor_percentile" icon={false}>
            p{Math.round(Number(found.percentile))}
          </Metric>
        </span>
      ) : null}
    </td>
  );
}

function FundamentalCell({ row, measureId }: { row: FactorRow; measureId: string }) {
  const found = rowValue(row, measureId);
  const info = meta(measureId);
  if (!found || found.value === null || found.percentile === null) {
    return (
      <td data-column={measureId} className="px-3 py-2 text-right text-neutral-500">
        <Metric termId={info.termId} icon={false}>
          {found?.reason === "not_meaningful" ? "n/m" : "n/a"}
        </Metric>
      </td>
    );
  }
  return (
    <td data-column={measureId} className="px-3 py-2 text-right tabular-nums">
      <Metric termId="factor_percentile" icon={false}>
        {ordinal(found.percentile).replace(" percentile", "")}
      </Metric>
      <span className="block text-xs text-neutral-500">
        <Metric termId={info.termId} icon={false}>
          {formatMeasure(found.value, found.unit, found.group)}
        </Metric>
      </span>
    </td>
  );
}

/**
 * Opportunity Radar (M2.2, ADR-030 F1): every universe instrument's trend, risk and relative
 * measures, and each equity's value and quality as percentiles of its own history, as known on
 * the chosen date. Sorted on the server from ?sort=&dir=. Candidates come with M2.4.
 */
export function OpportunityRadarView({
  data,
  knownOn,
  invalidKnownOn = false,
  sort = "ticker",
  dir = "asc",
}: {
  data: FactorsTable;
  knownOn?: string;
  invalidKnownOn?: boolean;
  sort?: string;
  dir?: SortDir;
}) {
  const fundamentalSort = (FUNDAMENTAL_COLUMNS as readonly string[]).includes(sort);
  const trendRows = sortRows(data.rows, fundamentalSort ? "ticker" : sort, fundamentalSort ? "asc" : dir);
  const equities = data.rows.filter((row) => row.instrument_type === "equity");
  const fundamentalRows = sortRows(equities, fundamentalSort ? sort : "ticker", fundamentalSort ? dir : "asc");
  const anyNotes = data.rows.some((row) => row.values.some((v) => v.notes > 0));
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_opportunity_radar" zh>
            Opportunity Radar
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          Where each instrument stands on trend, risk and, for the companies, value and quality, each
          against its own history. Candidates built from these, the convergence levels and the regime
          come next (<span data-identifier="">M2.4</span>).
        </p>
        <p role="note" className="text-xs text-neutral-500">
          <Metric termId="factor_percentile" icon={false}>
            {data.detail}
          </Metric>
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing what was known by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(data.known_at)}
          </Metric>{" "}
          under{" "}
          <Metric termId="factor_definition_set" icon={false}>
            factor definitions {data.definition_version}
          </Metric>
        </p>
      </header>
      <DemoBanner statuses={data.rows.map((row) => (row.price?.feed_status ?? null) as FeedStatus | null)} />

      <div className="space-y-2" data-block="trend">
        <h2 className="text-lg font-medium">
          <Metric termId="factor_snapshot" zh>
            Trend and risk
          </Metric>
        </h2>
        <div className="overflow-x-auto rounded border border-neutral-800">
          <table className="w-full min-w-[64rem] text-sm" aria-label="Trend and risk">
            <Header columns={TREND_COLUMNS} sort={fundamentalSort ? "" : sort} dir={dir} knownOn={knownOn} />
            <tbody>
              {trendRows.map((row) => (
                <tr key={row.ticker} data-ticker={row.ticker} className="border-b border-neutral-900">
                  <Ticker row={row} knownOn={knownOn} />
                  {TREND_COLUMNS.map((key) => (
                    <TrendCell key={key} row={row} measureId={key} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-neutral-500">
          <Metric termId="factor_percentile" icon={false}>
            Below each value, its percentile among the instrument&apos;s own month ends since 2016.
          </Metric>
          {anyNotes ? (
            <>
              {" "}
              <Metric termId="dividend_gap" icon={false}>
                * a dividend may be missing in the window; the instrument page says which.
              </Metric>
            </>
          ) : null}
        </p>
      </div>

      <div className="space-y-2" data-block="fundamentals">
        <h2 className="text-lg font-medium">
          <Metric termId="factor_percentile" zh>
            Value and quality against own history
          </Metric>
        </h2>
        <div className="overflow-x-auto rounded border border-neutral-800">
          <table className="w-full min-w-[56rem] text-sm" aria-label="Value and quality">
            <Header
              columns={FUNDAMENTAL_COLUMNS}
              sort={fundamentalSort ? sort : ""}
              dir={dir}
              knownOn={knownOn}
            />
            <tbody>
              {fundamentalRows.map((row) => (
                <tr key={row.ticker} data-ticker={row.ticker} className="border-b border-neutral-900">
                  <Ticker row={row} knownOn={knownOn} />
                  {FUNDAMENTAL_COLUMNS.map((key) => (
                    <FundamentalCell key={key} row={row} measureId={key} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-neutral-500">
          <Metric termId="factor_percentile" icon={false}>
            Each cell is the percentile of the value (below it) in the company&apos;s own month ends since
            2016: a high P/E or EV/sales percentile is dearer than usual, a high FCF yield percentile
            cheaper.
          </Metric>
        </p>
      </div>
    </section>
  );
}
