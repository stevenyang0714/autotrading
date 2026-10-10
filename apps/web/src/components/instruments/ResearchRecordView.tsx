import { Metric } from "@/components/Metric";
import { PeriodTable } from "@/components/instruments/PeriodTable";
import type { ResearchResult } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

const SECTIONS = [
  { section: "economics", label: "Economics" },
  { section: "quality", label: "Quality" },
  { section: "capital_allocation", label: "Capital allocation" },
];

/**
 * Research Record of the instrument page (M1.3b, ADR-024): economics, quality and capital
 * allocation for the last four quarters and five fiscal years, as known at the page's As
 * known on time. Every value opens its inputs and the filings behind them.
 */
export function ResearchRecordView({ result }: { result: ResearchResult }) {
  return (
    <section id="research-record" aria-labelledby="research-record-heading" className="space-y-3">
      <h2 id="research-record-heading" className="text-lg font-medium">
        <Metric termId="research_record" zh>
          Research Record
        </Metric>
      </h2>
      {result.status !== "ok" ? (
        <p role="alert" className="text-sm text-neutral-400">
          Data unavailable: the API could not be reached.
        </p>
      ) : result.data.periods.length === 0 ? (
        <p className="text-sm text-neutral-400">No fiscal years reported yet.</p>
      ) : (
        <>
          <p className="text-sm text-neutral-400">
            As known at{" "}
            <Metric termId="point_in_time" icon={false}>
              {formatSgtEt(result.data.known_at)}
            </Metric>
            . Open a value for its inputs and the filings behind them.
          </p>
          <PeriodTable
            label="Research Record"
            periods={result.data.periods}
            rows={result.data.rows}
            sections={SECTIONS}
            fallback="research_record"
          />
        </>
      )}
    </section>
  );
}
