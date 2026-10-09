import Link from "next/link";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";
import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import { DemoBanner } from "@/components/prices/DemoBanner";
import type { FeedStatus, ResearchDashboard, ResearchSummaryRow, SourceHealth } from "@/lib/api";
import { COLUMNS, GROUPS, type SortDir, cell, formatCell, sortRows } from "@/lib/research";
import { formatSgtEt } from "@/lib/time";

const HREF = "/dashboards/fundamental-research";

function sortHref(knownOn: string | undefined, key: string, dir: SortDir): string {
  const query = new URLSearchParams({ ...(knownOn ? { known_on: knownOn } : {}), sort: key, dir });
  return `${HREF}?${query.toString()}`;
}

function instrumentHref(ticker: string, knownOn: string | undefined): string {
  return `/instruments/${ticker}${knownOn ? `?known_on=${knownOn}` : ""}#research-record`;
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
  // A new column sorts high to low (ticker A to Z); the active one flips.
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

function Missing({ rows }: { rows: ResearchSummaryRow[] }) {
  const notes = rows.flatMap((row) =>
    COLUMNS.map((column) => ({ row, column, found: cell(row, column.key) })).filter(
      ({ found }) => found.value === null && found.detail,
    ),
  );
  if (notes.length === 0) return null;
  return (
    <details className="text-xs text-neutral-400" data-missing-reasons="">
      <summary className="cursor-pointer select-none">Why some values are n/m or unavailable</summary>
      <ul className="mt-1 space-y-0.5">
        {notes.map(({ row, column, found }) => (
          <li key={`${row.ticker}-${column.key}`}>
            <span data-identifier="">{row.ticker}</span>{" "}
            <Metric termId={column.termId} icon={false}>
              {column.label}: {found.status} ({found.detail})
            </Metric>
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * Fundamental Research dashboard (M1.3b, ADR-024 R1): every universe equity on one date, with
 * economics, quality, capital allocation, multiples and the DCF (model output, not fact).
 * Sorted on the server from ?sort=&dir=; each company opens its Research Record.
 */
export function ResearchDashboardView({
  data,
  sources,
  knownOn,
  invalidKnownOn = false,
  sort = "ticker",
  dir = "asc",
}: {
  data: ResearchDashboard;
  sources: SourceHealth[] | null;
  knownOn?: string;
  invalidKnownOn?: boolean;
  sort?: string;
  dir?: SortDir;
}) {
  const rows = sortRows(data.rows, sort, dir);
  const ariaSort = (key: string) =>
    sort === key ? (dir === "asc" ? "ascending" : "descending") : undefined;
  return (
    <section className="space-y-4">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="dashboard_fundamental_research" zh>
            Fundamental Research
          </Metric>
        </h1>
        <p className="text-sm text-neutral-400">
          Company economics, quality, capital allocation and valuation, each company over its
          latest four quarters.
        </p>
        <AsKnownOnForm href={HREF} knownOn={knownOn} invalid={invalidKnownOn} />
        <p className="text-sm text-neutral-400">
          Showing what was public by{" "}
          <Metric termId="point_in_time" icon={false}>
            {formatSgtEt(data.known_at)}
          </Metric>
        </p>
        <SourceFreshness sources={sources} ids={["sec_edgar", "alpaca_iex", "fred"]} />
      </header>
      <DemoBanner statuses={data.rows.map((row) => row.price.feed_status as FeedStatus | null)} />
      {rows.length === 0 ? (
        <p className="text-sm text-neutral-400">No companies yet.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-neutral-800">
          <table className="w-full min-w-[72rem] text-sm" aria-label="Fundamental Research">
            <thead>
              <tr className="text-xs text-neutral-400">
                <th rowSpan={2} className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left align-bottom font-normal">
                  <HeaderLink label="company" columnKey="ticker" sort={sort} dir={dir} knownOn={knownOn}>
                    Company
                  </HeaderLink>
                </th>
                {GROUPS.map(({ group, label, termId }) => (
                  <th
                    key={group}
                    colSpan={COLUMNS.filter((c) => c.group === group).length}
                    scope="colgroup"
                    className={`border-l border-neutral-800 px-3 pt-2 text-left font-normal ${
                      group === "model" ? "text-amber-300" : ""
                    }`}
                    data-group={group}
                  >
                    <Metric termId={termId} icon={false}>
                      {label}
                    </Metric>
                  </th>
                ))}
              </tr>
              <tr className="border-b border-neutral-800 text-xs text-neutral-400">
                {COLUMNS.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={ariaSort(column.key)}
                    className="px-3 py-2 text-right align-bottom font-normal"
                  >
                    <HeaderLink label={column.label} columnKey={column.key} sort={sort} dir={dir} knownOn={knownOn}>
                      <Metric termId={column.termId} icon={false}>
                        {column.label}
                      </Metric>
                    </HeaderLink>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ticker} data-ticker={row.ticker} className="border-b border-neutral-900">
                  <th scope="row" className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-left font-normal">
                    <Link
                      href={instrumentHref(row.ticker, knownOn)}
                      data-identifier=""
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      {row.ticker}
                    </Link>
                    <span className="block max-w-[11rem] truncate text-xs text-neutral-500">{row.name}</span>
                    {row.period ? (
                      <span className="block text-xs text-neutral-500">
                        <Metric
                          termId={row.period.kind === "ttm" ? "trailing_twelve_months" : "reporting_period"}
                          icon={false}
                        >
                          {row.period.kind === "ttm" ? "TTM" : "FY"} to {row.period.period_end}
                        </Metric>
                      </span>
                    ) : null}
                  </th>
                  {COLUMNS.map((column) => {
                    const found = cell(row, column.key);
                    return (
                      <td
                        key={column.key}
                        data-column={column.key}
                        className="px-3 py-2 text-right tabular-nums"
                        title={found.detail ?? undefined}
                      >
                        <Metric termId={column.termId} icon={false}>
                          {found.value !== null ? (
                            formatCell(found.value, column.unit)
                          ) : (
                            <span className="text-neutral-500">{found.status === "n/m" ? "n/m" : "n/a"}</span>
                          )}
                        </Metric>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-neutral-500">
        Each row is the company&apos;s latest four quarters (or its last fiscal year, right after a{" "}
        <span data-identifier="">10-K</span>); fiscal calendars differ. The DCF columns use each company&apos;s latest assumption
        version saved by this date and are{" "}
        <Metric termId="model_output" icon={false}>
          model output, not fact
        </Metric>
        . Open a company for five fiscal years and the filings behind every value.
      </p>
      <Missing rows={rows} />
    </section>
  );
}
