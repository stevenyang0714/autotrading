import { Metric } from "@/components/Metric";
import { ValuationInputItem } from "@/components/instruments/ValuationView";
import { type CompleteTermId, GLOSSARY } from "@/generated/glossary";
import type { ResearchPeriod, ResearchRow, ValuationMetric } from "@/lib/api";
import { exactReported, formatReported } from "@/lib/format";

/** A row of values by period (Research Record, Buybacks): one cell per period. */
export interface PeriodRow {
  metric_id: string;
  section: string;
  unit: ResearchRow["unit"];
  cells: ValuationMetric[];
}

function term(id: string, fallback: CompleteTermId): CompleteTermId {
  return id in GLOSSARY ? (id as CompleteTermId) : fallback;
}

function formatValue(value: string, unit: PeriodRow["unit"]): string {
  if (unit === "percent") return `${Number(value).toFixed(2)}%`;
  if (unit === "x") return `${Number(value).toFixed(2)}x`;
  if (unit === "flag") return Number(value) === 1 ? "yes" : "no";
  return formatReported(value, unit);
}

function status(cell: ValuationMetric): string {
  return cell.reason === "not_meaningful" ? "n/m" : "n/a";
}

/** A row whose every period is missing for the same reason: said once across the row. */
function uniformReason(row: PeriodRow): string | null {
  const [first, ...rest] = row.cells;
  if (!first || first.value !== null || !first.detail) return null;
  return rest.every((c) => c.value === null && c.detail === first.detail) ? first.detail : null;
}

function RecordCell({ cell, unit, termId }: { cell: ValuationMetric; unit: PeriodRow["unit"]; termId: CompleteTermId }) {
  if (cell.value === null) {
    return (
      <>
        <Metric termId={termId} icon={false}>
          <span className="text-neutral-500">{status(cell)}</span>
        </Metric>
        {cell.detail ? (
          <details className="text-xs text-neutral-400">
            <summary className="cursor-pointer select-none text-right">why</summary>
            <Metric termId={termId} icon={false}>
              {cell.detail}
            </Metric>
          </details>
        ) : null}
      </>
    );
  }
  return (
    <>
      <Metric termId={termId} icon={false}>
        <span title={unit === "USD" ? exactReported(cell.value, "USD") : undefined}>
          {formatValue(cell.value, unit)}
        </span>
      </Metric>
      {cell.inputs.length > 0 ? (
        <details className="text-xs text-neutral-400" data-inputs="">
          <summary className="cursor-pointer select-none text-right">inputs</summary>
          {cell.detail ? (
            <p className="mt-1 text-amber-300/80">
              <Metric termId={termId} icon={false}>
                {cell.detail}
              </Metric>
            </p>
          ) : null}
          <ul className="mt-1 min-w-[14rem] space-y-1.5 text-left">
            {cell.inputs.map((input) => (
              <ValuationInputItem key={`${input.name}-${input.period_end}`} input={input} fallback={termId} />
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}

/**
 * Values by period (M1.3b, M1.4a): TTM and fiscal years as columns, rows grouped in sections.
 * Each value opens its inputs and filings; a missing value says why, and a row missing for one
 * reason says it once.
 */
export function PeriodTable({
  label,
  periods,
  rows,
  sections,
  fallback,
}: {
  label: string;
  periods: ResearchPeriod[];
  rows: PeriodRow[];
  sections: { section: string; label: string | null }[];
  /** Term for a row without one of its own. */
  fallback: CompleteTermId;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[52rem] text-sm" aria-label={label}>
        <thead>
          <tr className="border-b border-neutral-800 text-xs text-neutral-400">
            <th scope="col" className="py-2 pr-3 text-left font-normal">
              Metric
            </th>
            {periods.map((period) => (
              <th
                key={period.period_end}
                scope="col"
                className="px-2 py-2 text-right font-normal whitespace-nowrap"
                data-period={period.kind}
              >
                <Metric termId={period.kind === "ttm" ? "trailing_twelve_months" : "reporting_period"} icon={false}>
                  {period.kind === "ttm" ? "TTM to" : "FY ending"} {period.period_end}
                </Metric>
              </th>
            ))}
          </tr>
        </thead>
        {sections.map(({ section, label: heading }) => (
          <tbody key={section} data-section={section}>
            {heading ? (
              <tr>
                <th
                  colSpan={periods.length + 1}
                  scope="colgroup"
                  className="pt-3 pb-1 text-left text-xs font-medium tracking-wide text-neutral-300 uppercase"
                >
                  {heading}
                </th>
              </tr>
            ) : null}
            {rows
              .filter((row) => row.section === section)
              .map((row) => {
                const termId = term(row.metric_id, fallback);
                const reason = uniformReason(row);
                return (
                  <tr key={row.metric_id} data-row={row.metric_id} className="border-b border-neutral-900 align-top">
                    <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                      <Metric termId={termId} icon={false} />
                    </th>
                    {reason ? (
                      <td colSpan={row.cells.length} className="px-2 py-1.5 text-left text-xs text-neutral-500">
                        <Metric termId={termId} icon={false}>
                          {row.cells[0].reason === "not_meaningful" ? "n/m" : "Data unavailable"}: {reason}
                        </Metric>
                      </td>
                    ) : (
                      row.cells.map((cell, index) => (
                        <td key={periods[index].period_end} className="px-2 py-1.5 text-right tabular-nums">
                          <RecordCell cell={cell} unit={row.unit} termId={termId} />
                        </td>
                      ))
                    )}
                  </tr>
                );
              })}
          </tbody>
        ))}
      </table>
    </div>
  );
}
