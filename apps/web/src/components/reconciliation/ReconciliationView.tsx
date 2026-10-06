import Link from "next/link";

import { Metric } from "@/components/Metric";
import { type CompleteTermId, GLOSSARY } from "@/generated/glossary";
import type {
  ReconciliationDetail,
  ReconciliationItem,
  ReconciliationList,
  ReconciliationOut,
  ReconciliationQuery,
} from "@/lib/api";
import { exactReported } from "@/lib/format";
import { formatSgtEt } from "@/lib/time";

const STATUS_TONE: Record<string, string> = {
  pass: "border-emerald-600/70 text-emerald-300",
  warn: "border-amber-600/70 text-amber-300",
  fail: "border-red-600/70 text-red-300",
  match: "border-emerald-700/60 text-emerald-300",
  ok: "border-emerald-700/60 text-emerald-300",
  restated_later: "border-sky-600/70 text-sky-300",
  flag: "border-amber-600/70 text-amber-300",
  mismatch: "border-red-600/70 text-red-300",
  missing: "border-red-600/70 text-red-300",
  extra: "border-red-600/70 text-red-300",
};

const STATUS_LABEL: Record<string, string> = {
  restated_later: "restated later",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <Metric termId="reconciliation_status" icon={false}>
      <span
        data-status={status}
        className={`inline-block rounded border px-1.5 py-0.5 text-[11px] leading-none ${STATUS_TONE[status] ?? "border-neutral-600"}`}
      >
        {STATUS_LABEL[status] ?? status}
      </span>
    </Metric>
  );
}

function Count({ value, label }: { value: number; label: string }) {
  return (
    <Metric termId="filing_reconciliation" icon={false}>
      <span className="whitespace-nowrap">
        {value} {label}
      </span>
    </Metric>
  );
}

/** Checked and matched always; every other count only when it is not zero. */
function Counts({ row }: { row: ReconciliationOut }) {
  const others: [number, string][] = [
    [row.mismatched, "mismatched"],
    [row.missing, "missing"],
    [row.extra, "extra"],
    [row.checks_failed, "checks failed"],
    [row.checks_flagged, "flagged"],
    [row.restated_later, "restated later"],
  ];
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
      <Count value={row.checked} label="checked" />
      <Count value={row.matched} label="matched" />
      {others
        .filter(([value]) => value > 0)
        .map(([value, label]) => (
          <span key={label} className={label === "restated later" ? "text-sky-300" : "text-amber-300"}>
            <Count value={value} label={label} />
          </span>
        ))}
    </span>
  );
}

function FilingLabel({ row }: { row: ReconciliationOut }) {
  return (
    <span className="space-x-1">
      <span data-identifier="">{row.ticker ?? "–"}</span>
      <span className="text-neutral-400">{row.company}</span>
    </span>
  );
}

function Accession({ row }: { row: ReconciliationOut }) {
  return (
    <Link
      href={`/system/reconciliation/${encodeURIComponent(row.accession)}`}
      data-identifier=""
      className="whitespace-nowrap underline-offset-2 hover:underline"
    >
      {row.form} {row.accession}
    </Link>
  );
}

/**
 * Reconciliation page (M1.1, ADR-021): each issuer's latest 10-K and 10-Q checked against the
 * filing's own XBRL. Statuses and counts go through glossary terms; accession numbers and
 * tickers are identifiers.
 */
export function ReconciliationView({
  data,
  query,
}: {
  data: ReconciliationList | null;
  query: ReconciliationQuery;
}) {
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_reconciliation">Reconciliation</Metric>
        </h1>
        <p className="max-w-3xl text-sm text-neutral-400">
          Each company&apos;s latest <span data-identifier="">10-K</span> and{" "}
          <span data-identifier="">10-Q</span>, read from the filing&apos;s own XBRL and compared
          with the values stored as known when the filing was accepted. Values a later filing
          changed count as restated later, not as errors.
        </p>
      </header>
      <form method="get" aria-label="Reconciliation filters" className="flex flex-wrap items-end gap-3 text-sm">
        <label className="space-y-1">
          <span className="block text-xs text-neutral-400">
            <Metric termId="reconciliation_status" icon={false}>
              Status
            </Metric>
          </span>
          <select name="status" defaultValue={query.status ?? ""} className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1">
            <option value="">All</option>
            <option value="pass">pass</option>
            <option value="warn">warn</option>
            <option value="fail">fail</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="block text-xs text-neutral-400">Form</span>
          <select
            name="form"
            data-identifier=""
            defaultValue={query.form ?? ""}
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1"
          >
            <option value="">10-K and 10-Q</option>
            <option value="10-K">10-K</option>
            <option value="10-Q">10-Q</option>
          </select>
        </label>
        <button type="submit" className="rounded border border-neutral-600 px-3 py-1 hover:bg-neutral-800">
          Show
        </button>
        <Link href="/system/reconciliation" className="px-1 py-1 text-neutral-400 hover:underline">
          Reset
        </Link>
      </form>
      {data === null ? (
        <p role="alert" className="rounded border border-red-800 bg-red-950/40 px-3 py-2 text-sm">
          Data unavailable: the API could not be reached.
        </p>
      ) : data.filings.length === 0 ? (
        <p className="text-sm text-neutral-500">No reconciled filings match these filters.</p>
      ) : (
        <>
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-left text-sm" aria-label="Reconciled filings">
              <thead className="text-xs text-neutral-400">
                <tr>
                  <th className="py-2 pr-4 font-medium">Company</th>
                  <th className="py-2 pr-4 font-medium">Filing</th>
                  <th className="py-2 pr-4 font-medium">
                    <Metric termId="filing_date" icon={false}>
                      Accepted
                    </Metric>
                  </th>
                  <th className="py-2 pr-4 font-medium">
                    <Metric termId="reconciliation_status" icon={false}>
                      Status
                    </Metric>
                  </th>
                  <th className="py-2 pr-4 font-medium">
                    <Metric termId="filing_reconciliation" icon={false}>
                      Checks
                    </Metric>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.filings.map((row) => (
                  <tr key={`${row.company}-${row.accession}`} data-filing="" className="border-t border-neutral-800 align-top">
                    <td className="py-2 pr-4">
                      <FilingLabel row={row} />
                    </td>
                    <td className="py-2 pr-4">
                      <Accession row={row} />
                    </td>
                    <td className="py-2 pr-4">
                      <Metric termId="filing_date" icon={false}>
                        {formatSgtEt(row.filing_published_at)}
                      </Metric>
                    </td>
                    <td className="py-2 pr-4">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="py-2 pr-4">
                      <Counts row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="space-y-3 lg:hidden" aria-label="Reconciled filings">
            {data.filings.map((row) => (
              <li key={`${row.company}-${row.accession}`} data-filing="" className="space-y-2 rounded border border-neutral-800 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <FilingLabel row={row} />
                  <StatusBadge status={row.status} />
                </div>
                <Accession row={row} />
                <p className="text-xs text-neutral-400">
                  Accepted{" "}
                  <Metric termId="filing_date" icon={false}>
                    {formatSgtEt(row.filing_published_at)}
                  </Metric>
                </p>
                <Counts row={row} />
              </li>
            ))}
          </ul>
          <p className="text-xs text-neutral-500">
            Methodology{" "}
            <Metric termId="filing_reconciliation" icon={false}>
              {data.methodology_version}
            </Metric>
          </p>
        </>
      )}
    </section>
  );
}

function term(metricId: string | null | undefined): CompleteTermId | null {
  return metricId && metricId in GLOSSARY ? (metricId as CompleteTermId) : null;
}

const CHECK_TERM: Record<string, CompleteTermId> = {
  fact: "filing_reconciliation",
  identity: "balance_identity",
  quarter: "quarterly_derived_value",
  split: "split_event",
};

function Value({ value, termId }: { value: string | null; termId: CompleteTermId }) {
  if (value === null) return <span className="text-neutral-600">–</span>;
  return (
    <Metric termId={termId} icon={false}>
      <span className="tabular-nums">{exactReported(value, "").trim()}</span>
    </Metric>
  );
}

function ItemRow({ item }: { item: ReconciliationItem }) {
  const metric = term(item.metric_id) ?? CHECK_TERM[item.check];
  return (
    <tr data-item={item.status} className="border-t border-neutral-800 align-top">
      <td className="py-2 pr-4">
        <StatusBadge status={item.status} />
      </td>
      <td className="py-2 pr-4">
        <Metric termId={CHECK_TERM[item.check]} icon={false}>
          {item.check}
        </Metric>
      </td>
      <td className="py-2 pr-4">{term(item.metric_id) ? <Metric termId={metric} /> : (item.metric_id ?? "")}</td>
      <td className="py-2 pr-4">
        {item.period_end ? (
          <Metric termId="reporting_period" icon={false}>
            {item.period_start ? `${item.period_start} to ` : ""}
            {item.period_end}
          </Metric>
        ) : null}
      </td>
      <td className="py-2 pr-4">
        <Value value={item.filing_value} termId={metric} />
      </td>
      <td className="py-2 pr-4">
        <Value value={item.stored_value} termId={metric} />
        {item.current_value !== null ? (
          <p className="text-xs text-sky-300">
            now <Value value={item.current_value} termId={metric} />
          </p>
        ) : null}
      </td>
      <td className="py-2 pr-4 text-xs text-neutral-400">
        {item.stored_accession ? <span data-identifier="">{item.stored_accession}</span> : null}
        {item.detail ? (
          <p>
            <Metric termId={CHECK_TERM[item.check]} icon={false}>
              {item.detail}
            </Metric>
          </p>
        ) : null}
      </td>
    </tr>
  );
}

/** One filing's reconciliation items, problems first. */
export function ReconciliationDetailView({ data }: { data: ReconciliationDetail }) {
  const row = data.filing;
  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <p className="text-sm">
          <Link href="/system/reconciliation" className="text-neutral-400 hover:underline">
            <Metric termId="page_reconciliation" icon={false}>
              Reconciliation
            </Metric>
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">
          <FilingLabel row={row} /> <span data-identifier="">{row.form}</span>
        </h1>
        <p className="flex flex-wrap items-center gap-3 text-sm text-neutral-400">
          <StatusBadge status={row.status} />
          {row.filing_url ? (
            <a href={row.filing_url} target="_blank" rel="noreferrer" data-identifier="" className="hover:underline">
              {row.accession}
            </a>
          ) : (
            <span data-identifier="">{row.accession}</span>
          )}
          <a href={row.instance_url} target="_blank" rel="noreferrer" className="hover:underline">
            filing XBRL
          </a>
          <span>
            accepted{" "}
            <Metric termId="filing_date" icon={false}>
              {formatSgtEt(row.filing_published_at)}
            </Metric>
          </span>
        </p>
        <Counts row={row} />
      </header>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[56rem] text-left text-sm" aria-label="Reconciliation items">
          <thead className="text-xs text-neutral-400">
            <tr>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 pr-4 font-medium">Check</th>
              <th className="py-2 pr-4 font-medium">Metric</th>
              <th className="py-2 pr-4 font-medium">Period</th>
              <th className="py-2 pr-4 font-medium">In the filing</th>
              <th className="py-2 pr-4 font-medium">Stored then</th>
              <th className="py-2 pr-4 font-medium">Note</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item, i) => (
              <ItemRow key={`${item.check}-${item.metric_id}-${item.period_start}-${item.period_end}-${i}`} item={item} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
