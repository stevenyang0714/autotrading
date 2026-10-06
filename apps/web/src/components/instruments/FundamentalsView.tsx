import Link from "next/link";
import type { ReactNode } from "react";

import { Metric } from "@/components/Metric";
import { SourceFreshness } from "@/components/SourceFreshness";
import type { CompleteTermId } from "@/generated/glossary";
import type {
  EntityOut,
  FactCell,
  FactTable,
  FilingRef,
  Fundamentals,
  SourceHealth,
} from "@/lib/api";
import { exactReported, formatReported } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

import { AsKnownOnForm } from "@/components/AsKnownOnForm";

type TableMetric = Extract<
  CompleteTermId,
  | "revenue"
  | "gross_profit"
  | "operating_income"
  | "net_income"
  | "eps_diluted"
  | "diluted_shares"
  | "operating_cash_flow"
  | "capex"
  | "share_repurchases"
  | "stock_based_compensation"
  | "cash"
  | "long_term_debt_current"
  | "long_term_debt_noncurrent"
  | "commercial_paper"
>;

const TABLE_METRICS = new Set<string>([
  "revenue",
  "gross_profit",
  "operating_income",
  "net_income",
  "eps_diluted",
  "diluted_shares",
  "operating_cash_flow",
  "capex",
  "share_repurchases",
  "stock_based_compensation",
  "cash",
  "long_term_debt_current",
  "long_term_debt_noncurrent",
  "commercial_paper",
]);

function asTableMetric(metricId: string): TableMetric | null {
  return TABLE_METRICS.has(metricId) ? (metricId as TableMetric) : null;
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
 * Instrument page body (M0.5b). Values are SEC XBRL facts as known at `data.known_at`
 * (ADR-012); each links to its filing. Every number renders through <Metric>; tickers,
 * accession numbers, forms and CIKs are identifiers ([data-identifier]).
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
    </section>
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
                        {cell && cell.kind !== "derived" ? (
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
