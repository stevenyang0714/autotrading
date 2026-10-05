import type { ReactNode } from "react";

import { Metric } from "@/components/Metric";
import type { DataHealthData, DeadLetter, IngestionRun, SourceHealth } from "@/lib/api";
import { formatDuration, formatSgtEt } from "@/lib/time";

import { ACCESS, CADENCE, FRESHNESS, LICENSE, RUN_STATUS, TONE_CLASS, type Tone } from "./labels";

/**
 * Data Health page body (M0.4). Every status, count, duration and timestamp renders through
 * <Metric>; names, URLs and job ids are identifiers ([data-identifier]), not metrics.
 * `data` is null when the API is unreachable: no numbers are shown at all.
 */
export function DataHealthView({ data }: { data: DataHealthData | null }) {
  return (
    <section className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_data_health">Data Health</Metric>
        </h1>
        {data ? (
          <p className="text-sm text-neutral-500">
            Checked{" "}
            <Metric termId="as_of" icon={false}>
              {formatSgtEt(data.report.checked_at)}
            </Metric>
          </p>
        ) : null}
      </header>
      {data ? <Body data={data} /> : <Unavailable />}
    </section>
  );
}

function Unavailable() {
  return (
    <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
      <p className="font-medium">Data unavailable</p>
      <p className="mt-1 text-neutral-400">
        The API could not be reached, so no source status is shown. Check the stack with{" "}
        <code>make ps</code> and the API health page.
      </p>
    </div>
  );
}

function Body({ data }: { data: DataHealthData }) {
  return (
    <>
      <Sources sources={data.report.sources} />
      <Runs runs={data.runs} />
      <DeadLetters letters={data.deadLetters} />
    </>
  );
}

// ---------- sources ----------

function Sources({ sources }: { sources: SourceHealth[] }) {
  return (
    <section aria-labelledby="sources-heading" className="space-y-3">
      <h2 id="sources-heading" className="text-lg font-medium">
        Sources
      </h2>
      {sources.length === 0 ? (
        <p className="text-sm text-neutral-500">No sources registered. Run make migrate.</p>
      ) : (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-neutral-400">
                <tr>
                  <Th>Source</Th>
                  <Th><Metric termId="source_tier">Tier</Metric></Th>
                  <Th><Metric termId="license_status">License</Metric></Th>
                  <Th><Metric termId="access_status">Access</Metric></Th>
                  <Th><Metric termId="data_freshness">Freshness</Metric></Th>
                  <Th><Metric termId="update_cadence">Cadence</Metric></Th>
                  <Th><Metric termId="freshness_sla">SLA</Metric></Th>
                  <Th><Metric termId="rate_limit">Rate limit</Metric></Th>
                  <Th><Metric termId="as_of">Last success</Metric></Th>
                  <Th><Metric termId="ingestion_status">Last run</Metric></Th>
                  <Th><Metric termId="dead_letter">Dead letters</Metric></Th>
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source.id} className="border-t border-neutral-800 align-top">
                    <td className="min-w-[14rem] max-w-[18rem] py-2 pr-4">
                      <SourceName source={source} />
                    </td>
                    <Td><TierValue source={source} /></Td>
                    <Td><LicenseValue source={source} /></Td>
                    <Td><AccessValue source={source} /></Td>
                    <Td><FreshnessValue source={source} /></Td>
                    <Td><CadenceValue source={source} /></Td>
                    <Td><SlaValue source={source} /></Td>
                    <Td><RateValue source={source} /></Td>
                    <Td><LastSuccessValue source={source} /></Td>
                    <Td><LastRunValue source={source} /></Td>
                    <Td><DeadLetterCount source={source} /></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="space-y-3 md:hidden" aria-label="Sources">
            {sources.map((source) => (
              <li key={source.id} className="rounded border border-neutral-800 p-3 text-sm">
                <SourceName source={source} />
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2">
                  <Item term={<Metric termId="data_freshness">Freshness</Metric>}>
                    <FreshnessValue source={source} />
                  </Item>
                  <Item term={<Metric termId="source_tier">Tier</Metric>}>
                    <TierValue source={source} />
                  </Item>
                  <Item term={<Metric termId="license_status">License</Metric>}>
                    <LicenseValue source={source} />
                  </Item>
                  <Item term={<Metric termId="access_status">Access</Metric>}>
                    <AccessValue source={source} />
                  </Item>
                  <Item term={<Metric termId="freshness_sla">SLA</Metric>}>
                    <SlaValue source={source} />
                  </Item>
                  <Item term={<Metric termId="rate_limit">Rate limit</Metric>}>
                    <RateValue source={source} />
                  </Item>
                  <Item term={<Metric termId="as_of">Last success</Metric>}>
                    <LastSuccessValue source={source} />
                  </Item>
                  <Item term={<Metric termId="ingestion_status">Last run</Metric>}>
                    <LastRunValue source={source} />
                  </Item>
                </dl>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function SourceName({ source }: { source: SourceHealth }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noreferrer"
      data-identifier=""
      className="font-medium underline-offset-2 hover:underline"
    >
      {source.name}
    </a>
  );
}

function TierValue({ source }: { source: SourceHealth }) {
  return (
    <Metric termId="source_tier" icon={false}>
      Tier {source.tier}
    </Metric>
  );
}

function LicenseValue({ source }: { source: SourceHealth }) {
  return (
    <Metric termId="license_status" icon={false}>
      {LICENSE[source.license_status] ?? source.license_status}
    </Metric>
  );
}

function AccessValue({ source }: { source: SourceHealth }) {
  const [label, tone] = ACCESS[source.access_status] ?? [source.access_status, "muted"];
  return (
    <Metric termId="access_status" icon={false}>
      <Badge tone={tone}>{label}</Badge>
    </Metric>
  );
}

function FreshnessValue({ source }: { source: SourceHealth }) {
  const [label, tone] = FRESHNESS[source.freshness ?? "disabled"];
  return (
    <Metric termId="data_freshness" icon={false}>
      <Badge tone={tone}>{label}</Badge>
    </Metric>
  );
}

function CadenceValue({ source }: { source: SourceHealth }) {
  return (
    <Metric termId="update_cadence" icon={false}>
      {CADENCE[source.update_cadence] ?? source.update_cadence}
    </Metric>
  );
}

function SlaValue({ source }: { source: SourceHealth }) {
  return (
    <Metric termId="freshness_sla" icon={false}>
      {formatDuration(source.freshness_sla_seconds)}
    </Metric>
  );
}

function RateValue({ source }: { source: SourceHealth }) {
  return (
    <Metric termId="rate_limit" icon={false}>
      {Number(source.rate_limit_per_second)}/s, burst {source.rate_limit_burst}
    </Metric>
  );
}

function LastSuccessValue({ source }: { source: SourceHealth }) {
  return (
    <Metric termId="as_of" icon={false}>
      {source.last_success_at ? formatSgtEt(source.last_success_at) : "Never"}
    </Metric>
  );
}

function LastRunValue({ source }: { source: SourceHealth }) {
  if (!source.last_run) {
    return (
      <Metric termId="ingestion_status" icon={false}>
        None
      </Metric>
    );
  }
  return <RunStatus run={source.last_run} />;
}

function DeadLetterCount({ source }: { source: SourceHealth }) {
  return (
    <Metric termId="dead_letter" icon={false}>
      {source.open_dead_letters}
    </Metric>
  );
}

// ---------- runs ----------

function Runs({ runs }: { runs: IngestionRun[] }) {
  return (
    <section aria-labelledby="runs-heading" className="space-y-3">
      <h2 id="runs-heading" className="text-lg font-medium">
        Recent ingestion runs
      </h2>
      {runs.length === 0 ? (
        <p className="text-sm text-neutral-500">
          No ingestion runs yet. Runs appear once a source is enabled; SEC EDGAR is next.
        </p>
      ) : (
        <ul className="divide-y divide-neutral-800 text-sm" aria-label="Recent ingestion runs">
          {runs.map((run) => (
            <li key={run.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
              <RunStatus run={run} />
              <span data-identifier="" className="text-neutral-300">
                {run.source_id} · {run.job}
              </span>
              <Metric termId="as_of" icon={false} className="text-neutral-500">
                {formatSgtEt(run.finished_at ?? run.created_at)}
              </Metric>
              {run.error_class ? (
                <Metric termId="ingestion_status" icon={false} className="text-neutral-500">
                  {run.error_class}
                </Metric>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RunStatus({ run }: { run: IngestionRun }) {
  const [label, tone] = RUN_STATUS[run.status] ?? [run.status, "muted"];
  return (
    <Metric termId="ingestion_status" icon={false}>
      <Badge tone={tone}>{label}</Badge>
    </Metric>
  );
}

// ---------- dead letters ----------

function DeadLetters({ letters }: { letters: DeadLetter[] }) {
  return (
    <section aria-labelledby="dead-letters-heading" className="space-y-3">
      <h2 id="dead-letters-heading" className="text-lg font-medium">
        <Metric termId="dead_letter">Open dead letters</Metric>
      </h2>
      {letters.length === 0 ? (
        <p className="text-sm text-neutral-500">No open dead letters.</p>
      ) : (
        <ul className="divide-y divide-neutral-800 text-sm" aria-label="Open dead letters">
          {letters.map((letter) => (
            <li key={letter.id} className="space-y-1 py-2">
              <span data-identifier="" className="block text-neutral-300">
                {letter.source_id} · {letter.job}
              </span>
              <span className="flex flex-wrap gap-x-4">
                <Metric termId="dead_letter" icon={false}>
                  {letter.attempts} attempts
                </Metric>
                <Metric termId="as_of" icon={false} className="text-neutral-500">
                  {formatSgtEt(letter.failed_at)}
                </Metric>
              </span>
              {letter.error_message ? (
                <Metric termId="dead_letter" icon={false} className="text-neutral-500">
                  {letter.error_class}: {letter.error_message}
                </Metric>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------- primitives ----------

function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${TONE_CLASS[tone]}`} />
      {children}
    </span>
  );
}

function Th({ children }: { children: ReactNode }) {
  return <th className="whitespace-nowrap py-2 pr-4 font-medium">{children}</th>;
}

function Td({ children }: { children: ReactNode }) {
  return <td className="whitespace-nowrap py-2 pr-4">{children}</td>;
}

function Item({ term, children }: { term: ReactNode; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-neutral-500">{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}
