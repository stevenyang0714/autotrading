import Link from "next/link";
import type { ReactNode } from "react";

import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import { Sparkline } from "@/components/Sparkline";
import { type CompleteTermId, GLOSSARY } from "@/generated/glossary";
import type {
  DerivedCell,
  EntityOut,
  FactCell,
  FactTable,
  FilingRef,
  Fundamentals,
  QuarterTable,
  SourceHealth,
  SplitAdjusted,
  SplitOut,
} from "@/lib/api";
import { exactReported, formatReported } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";

type TableMetric = CompleteTermId;

/** Rows are shown when their metric has a complete glossary term (M0.4 rule): the API may
 * add a metric before its tooltip exists, and such a row stays hidden rather than unexplained. */
function asTableMetric(metricId: string): TableMetric | null {
  return metricId in GLOSSARY ? (metricId as TableMetric) : null;
}

interface Props {
  data: Fundamentals;
  /** The "As known on" date from the URL, if any (YYYY-MM-DD). */
  knownOn?: string;
  /** Set when the URL carried a date that is not a real calendar date. */
  invalidKnownOn?: boolean;
  sources?: SourceHealth[] | null;
  /** The price block (M0.7), shown under the header; absent for instruments without prices. */
  prices?: ReactNode;
  /** Recent news stories (M0.8), shown after the price block. */
  news?: ReactNode;
}

/**
 * Instrument page body (M0.5b, M1.1). Values are SEC XBRL facts as known at `data.known_at`
 * (ADR-012); each links to its filing. Derived values (free cash flow, debt, quarters, TTM)
 * show their inputs; per-share values show their split-adjusted value beside the reported one
 * (ADR-021). Every number renders through <Metric>; tickers, accession numbers, forms and CIKs
 * are identifiers ([data-identifier]).
 */
export function FundamentalsView({ data, knownOn, invalidKnownOn, sources, prices, news }: Props) {
  const newest = [...data.annual.rows, ...data.balance_sheet.rows]
    .flatMap((row) => row.cells)
    .map((cell) => (cell && cell.kind !== "derived" ? cell.filing.published_at : undefined))
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);
  const names = new Map(data.entities.map((entity) => [entity.id, entity]));
  const current = data.entities[0];
  return (
    <section className="space-y-8">
      <header className="space-y-3">
        <p className="text-sm">
          <Link href="/instruments" className="text-neutral-400 hover:underline">
            <Metric termId="page_instruments" icon={false}>
              Instruments
            </Metric>
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">
          <span data-identifier="">{data.ticker}</span>{" "}
          <span className="text-neutral-400">·</span> {data.issuer.name}
        </h1>
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
          {data.exchange ? <span data-identifier="">{data.exchange}</span> : null}
          {data.issuer.cik ? <span data-identifier="">CIK {data.issuer.cik}</span> : null}
          {data.issuer.id !== current.id ? (
            <span>
              Issuer at that time;{" "}
              <Metric termId="predecessor_issuer" icon={false}>
                today {current.name}
              </Metric>
            </span>
          ) : null}
        </p>
        <AsKnownOnForm
          href={`/instruments/${encodeURIComponent(data.ticker)}`}
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
              {" · "}last SEC refresh{" "}
              <Metric termId="as_of" icon={false}>
                {formatSgtEt(data.last_refresh_at)}
              </Metric>
            </>
          ) : null}
        </p>
        {sources !== undefined ? (
          <SourceFreshness
            sources={sources}
            ids={[...(prices ? ["sec_edgar", "alpaca_iex"] : ["sec_edgar"]), ...(news ? ["gdelt"] : [])]}
            newestPublishedAt={knownOn ? null : newest}
          />
        ) : null}
        <Predecessors entities={data.entities.slice(1)} />
      </header>

      {prices}

      {news}

      <Table
        id="annual"
        title="Annual results"
        table={data.annual}
        names={names}
        issuerId={current.id}
        header={(start, end) => (
          <Metric termId="reporting_period" icon={false}>
            <span title={`${start} to ${end}`}>FY ending {end}</span>
          </Metric>
        )}
      />
      <Table
        id="balance-sheet"
        title="Balance sheet"
        table={data.balance_sheet}
        names={names}
        issuerId={current.id}
        header={(_start, end) => (
          <Metric termId="reporting_period" icon={false}>
            As of {end}
          </Metric>
        )}
      />
      <Latest rows={data.latest} splits={data.splits} />
      <Quarterly table={data.quarterly} />
      <PerShareHistory table={data.per_share_history} names={names} issuerId={current.id} />
    </section>
  );
}

function Latest({ rows, splits }: { rows: Fundamentals["latest"]; splits: SplitOut[] }) {
  if (rows.length === 0 && splits.length === 0) return null;
  return (
    <section aria-labelledby="latest-heading" className="space-y-2">
      <h2 id="latest-heading" className="text-lg font-medium">
        Latest reported
      </h2>
      <ul className="space-y-2 text-sm" aria-label="Latest reported values">
        {rows.map((row) => {
          const metric = asTableMetric(row.metric_id);
          const cell = row.cells[0];
          if (!metric || !cell || cell.kind === "derived") return null;
          return (
            <li key={row.metric_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Metric termId={metric} />
              <Metric termId={metric} icon={false}>
                <span className="tabular-nums" title={exactReported(cell.value, cell.unit)}>
                  {formatReported(cell.value, cell.unit)}
                </span>{" "}
                <span className="text-neutral-400">as of {cell.period_end}</span>
              </Metric>
              <FilingLink filing={cell.filing} inline />
              {cell.split_adjusted ? <SplitLine adjusted={cell.split_adjusted} unit={cell.unit} /> : null}
            </li>
          );
        })}
        {splits.length > 0 ? (
          <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <Metric termId="split_event">Stock splits</Metric>
            {splits.map((split) => (
              <span key={split.ex_date}>
                <Metric termId="split_event" icon={false}>
                  {Number(split.new_rate)}-for-{Number(split.old_rate)} on {split.ex_date}
                </Metric>{" "}
                (
                <a
                  href={split.source_url}
                  target="_blank"
                  rel="noreferrer"
                  data-identifier=""
                  className="underline-offset-2 hover:underline"
                >
                  {split.source_id === "sec_edgar" ? "8-K" : "Alpaca"}
                </a>
                )
              </span>
            ))}
          </li>
        ) : null}
      </ul>
    </section>
  );
}

function Quarterly({ table }: { table: QuarterTable }) {
  return (
    <section aria-labelledby="quarterly-heading" className="space-y-3">
      <h2 id="quarterly-heading" className="text-lg font-medium">
        <Metric termId="quarterly_derived_value">Quarterly</Metric>
      </h2>
      {table.periods.length === 0 ? (
        <p className="text-sm text-neutral-500">No quarters as of this date.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[48rem] text-left text-sm" aria-label="Quarterly">
            <thead className="text-xs text-neutral-400">
              <tr>
                <th className="py-2 pr-4 font-medium">Metric</th>
                {table.periods.map((period) => (
                  <th key={period.period_end} className="py-2 pr-4 font-medium">
                    <Metric termId="reporting_period" icon={false}>
                      <span title={`${period.period_start ?? ""} to ${period.period_end}`}>
                        Quarter to {period.period_end}
                      </span>
                    </Metric>
                  </th>
                ))}
                <th className="py-2 pr-4 font-medium">
                  <Metric termId="trailing_twelve_months">TTM</Metric>
                </th>
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => {
                const metric = asTableMetric(row.metric_id);
                if (!metric) return null;
                return (
                  <tr key={row.metric_id} className="border-t border-neutral-800 align-top">
                    <th scope="row" className="py-2 pr-4 font-normal">
                      <Metric termId={metric} />
                    </th>
                    {row.cells.map((cell, i) => (
                      <td key={table.periods[i].period_end} className="py-2 pr-4">
                        {cell ? (
                          <Derived metric={metric} cell={cell} />
                        ) : (
                          <span className="text-neutral-500">Not available</span>
                        )}
                      </td>
                    ))}
                    <td className="py-2 pr-4" data-ttm="">
                      {row.ttm ? <Derived metric={metric} cell={row.ttm} /> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PerShareHistory({
  table,
  names,
  issuerId,
}: {
  table: FactTable;
  names: Map<string, EntityOut>;
  issuerId: string;
}) {
  const eps = table.rows.find((row) => row.metric_id === "eps_diluted");
  const points = (eps?.cells ?? [])
    .map((cell, i) => {
      if (!cell || cell.kind === "derived") return null;
      return {
        day: table.periods[i].period_end,
        value: cell.split_adjusted ? cell.split_adjusted.value : cell.value,
      };
    })
    .filter((p): p is { day: string; value: string } => p !== null)
    .reverse();
  return (
    <section aria-labelledby="per-share-heading" className="space-y-3">
      <Table
        id="per-share"
        title="Per-share history"
        table={table}
        names={names}
        issuerId={issuerId}
        header={(start, end) => (
          <Metric termId="reporting_period" icon={false}>
            <span title={`${start} to ${end}`}>FY ending {end}</span>
          </Metric>
        )}
      />
      {points.length > 1 ? (
        <div className="max-w-md">
          <Sparkline
            points={points}
            termId="split_adjusted"
            label="Diluted EPS, split-adjusted"
            format={(v) => `$${v.toFixed(2)}`}
            zeroLine
          />
        </div>
      ) : null}
    </section>
  );
}

/** How a derived value was computed; the summary opens its inputs. */
const METHODS: Record<string, string> = {
  reported: "as reported",
  ytd_difference: "year-to-date difference",
  year_minus_9_months: "year minus nine months",
  quarter_sum: "sum of four quarters",
  "operating_cash_flow - capex": "operating cash flow − capex",
  "long-term debt (non-current + current) + commercial paper": "sum of debt components",
  "total debt - cash": "total debt − cash",
};

function Derived({ metric, cell }: { metric: TableMetric; cell: DerivedCell }) {
  const zero = cell.inputs.filter((input) => input.assumed_zero);
  return (
    <div className="space-y-1" data-cell={metric} data-derived="">
      <div className="flex flex-wrap items-center gap-2">
        <Metric termId={metric} icon={false}>
          <span title={exactReported(cell.value, cell.unit)} className="tabular-nums">
            {formatReported(cell.value, cell.unit)}
          </span>
        </Metric>
      </div>
      {cell.split_adjusted ? <SplitLine adjusted={cell.split_adjusted} unit={cell.unit} /> : null}
      {zero.length > 0 ? (
        <p className="text-xs text-amber-300">
          <Metric termId="total_debt" icon={false}>
            Not reported, counted as zero:{" "}
            {zero.map((input) => GLOSSARY[input.metric_id as TableMetric]?.display_name ?? input.metric_id).join(", ")}
          </Metric>
        </p>
      ) : null}
      <details className="text-xs text-neutral-400">
        <summary className="cursor-pointer select-none">
          {METHODS[cell.method] ?? cell.method}
        </summary>
        <ul className="mt-1 space-y-1">
          {cell.inputs
            .filter((input) => !input.assumed_zero && input.value !== null)
            .map((input, i) => {
              const term = asTableMetric(input.metric_id) ?? metric;
              return (
                <li key={`${input.metric_id}-${input.period_end}-${i}`}>
                  <Metric termId={term} icon={false}>
                    {GLOSSARY[term].display_name}{" "}
                    <span className="tabular-nums">
                      {formatReported(input.value ?? "0", cell.unit)}
                    </span>{" "}
                    ({input.period_start ? `${input.period_start} to ` : ""}
                    {input.period_end})
                  </Metric>
                  {input.filing ? (
                    <>
                      {" "}
                      · <FilingLink filing={input.filing} inline />
                    </>
                  ) : null}
                </li>
              );
            })}
        </ul>
      </details>
    </div>
  );
}

function SplitLine({ adjusted, unit }: { adjusted: SplitAdjusted; unit: string }) {
  const perShare = unit === "USD/shares";
  return (
    <p className="text-xs text-sky-300">
      <Metric termId="split_adjusted" icon={false}>
        <span title={`Splits after the filing: ${adjusted.splits.join(", ")}`}>
          {formatReported(adjusted.value, unit)} split-adjusted ({perShare ? "÷" : "×"}
          {adjusted.factor})
        </span>
      </Metric>
    </p>
  );
}

function Predecessors({ entities }: { entities: EntityOut[] }) {
  if (entities.length === 0) return null;
  return (
    <ul className="space-y-1 text-sm text-neutral-400" aria-label="Predecessor issuers">
      {entities.map((entity) => (
        <li key={entity.id}>
          History includes{" "}
          <Metric termId="predecessor_issuer" icon={false}>
            {entity.name}
          </Metric>
          {entity.cik ? (
            <>
              {" "}
              (<span data-identifier="">CIK {entity.cik}</span>)
            </>
          ) : null}
          {entity.succeeded_at ? (
            <>
              , succeeded on{" "}
              <Metric termId="as_of" icon={false}>
                {formatSgtEt(entity.succeeded_at)}
              </Metric>
            </>
          ) : null}
          {entity.evidence_url && entity.evidence_accession ? (
            <>
              {" "}
              per{" "}
              <a
                href={entity.evidence_url}
                target="_blank"
                rel="noreferrer"
                data-identifier=""
                className="underline-offset-2 hover:underline"
              >
                {entity.evidence_accession}
              </a>
            </>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

interface TableProps {
  id: string;
  title: string;
  table: FactTable;
  names: Map<string, EntityOut>;
  issuerId: string;
  header: (start: string, end: string) => ReactNode;
}

function Table({ id, title, table, names, issuerId, header }: TableProps) {
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-3">
      <h2 id={`${id}-heading`} className="text-lg font-medium">
        {title}
      </h2>
      {table.periods.length === 0 ? (
        <p className="text-sm text-neutral-500">Not reported as of this date.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm" aria-label={title}>
            <thead className="text-xs text-neutral-400">
              <tr>
                <th className="py-2 pr-4 font-medium">Metric</th>
                {table.periods.map((period) => (
                  <th key={period.period_end} className="py-2 pr-4 font-medium">
                    {header(period.period_start ?? "", period.period_end)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => {
                const metric = asTableMetric(row.metric_id);
                if (!metric) return null;
                return (
                  <tr key={row.metric_id} className="border-t border-neutral-800 align-top">
                    <th scope="row" className="py-2 pr-4 font-normal">
                      <Metric termId={metric} />
                    </th>
                    {row.cells.map((cell, i) => (
                      <td key={table.periods[i].period_end} className="py-2 pr-4">
                        {cell && cell.kind === "derived" ? (
                          <Derived metric={metric} cell={cell} />
                        ) : cell ? (
                          <Cell
                            metric={metric}
                            cell={cell}
                            reporter={cell.reported_by === issuerId ? null : names.get(cell.reported_by)}
                          />
                        ) : (
                          <span className="text-neutral-500">Not reported</span>
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Cell({
  metric,
  cell,
  reporter,
}: {
  metric: TableMetric;
  cell: FactCell;
  reporter: EntityOut | null | undefined;
}) {
  return (
    <div className="space-y-1" data-cell={metric}>
      <div className="flex flex-wrap items-center gap-2">
        <Metric termId={metric} icon={false}>
          <span title={exactReported(cell.value, cell.unit)} className="tabular-nums">
            {formatReported(cell.value, cell.unit)}
          </span>
        </Metric>
        {cell.restated ? (
          <Metric termId="restated_flag" icon={false}>
            <span className="rounded border border-amber-600/60 px-1.5 text-xs text-amber-300">
              Restated
            </span>
          </Metric>
        ) : null}
      </div>
      {cell.split_adjusted ? <SplitLine adjusted={cell.split_adjusted} unit={cell.unit} /> : null}
      {cell.source_concept?.endsWith("(sum of classes)") ? (
        <p className="text-xs text-neutral-400">
          <Metric termId={metric} icon={false}>
            sum of share classes
          </Metric>
        </p>
      ) : null}
      <FilingLink filing={cell.filing} />
      {cell.previous ? (
        <p className="text-xs text-neutral-400">
          was{" "}
          <Metric termId={metric} icon={false}>
            <span title={exactReported(cell.previous.value, cell.unit)}>
              {formatReported(cell.previous.value, cell.unit)}
            </span>
          </Metric>{" "}
          · <FilingLink filing={cell.previous.filing} inline />
        </p>
      ) : null}
      {reporter ? (
        <p className="text-xs text-neutral-400">
          by{" "}
          <Metric termId="predecessor_issuer" icon={false}>
            {reporter.name}
          </Metric>
        </p>
      ) : null}
    </div>
  );
}

function FilingLink({ filing, inline = false }: { filing: FilingRef; inline?: boolean }) {
  const link = (
    <a
      href={filing.url}
      target="_blank"
      rel="noreferrer"
      data-identifier=""
      className="whitespace-nowrap underline-offset-2 hover:underline"
      title={`Accepted ${formatSgtEt(filing.published_at)}`}
    >
      {filing.form ? `${filing.form} ` : ""}
      {filing.accession}
    </a>
  );
  if (inline) return link;
  return (
    <p className="text-xs text-neutral-400">
      <Metric termId="accession_number" icon={false}>
        {link}
      </Metric>
    </p>
  );
}
