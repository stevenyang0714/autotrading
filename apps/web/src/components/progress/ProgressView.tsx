import { Metric } from "@/components/Metric";
import type { Progress } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

const STATUS: Record<string, [string, string]> = {
  done: ["Done", "bg-emerald-500"],
  in_progress: ["In progress", "bg-sky-500"],
  not_started: ["Not started", "bg-neutral-600"],
};

const CURRENT_KEYS = ["Phase", "Sub-milestone", "Next", "Blockers", "Open decisions due soon"];

/**
 * Build progress (M0.6, ADR-016), parsed live from the project documents. Text quoted from the
 * documents renders under the term that names its source (dev_log, open_decision, ...).
 */
export function ProgressView({ data }: { data: Progress | null }) {
  return (
    <section className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_progress" zh>
            Build Progress
          </Metric>
        </h1>
        {data ? (
          <p className="text-sm text-neutral-500">
            Read from the project documents at{" "}
            <Metric termId="as_of" icon={false}>
              {formatSgtEt(data.read_at)}
            </Metric>
            ; refresh the page to see the latest.
          </p>
        ) : null}
      </header>
      {data === null ? (
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not read the project documents.</p>
        </div>
      ) : (
        <Body data={data} />
      )}
    </section>
  );
}

function Body({ data }: { data: Progress }) {
  const done = data.milestones.filter((m) => m.status === "done").length;
  return (
    <>
      <section aria-labelledby="current-heading" className="space-y-2">
        <h2 id="current-heading" className="text-lg font-medium">
          Now
        </h2>
        <dl className="grid gap-x-4 gap-y-1 text-sm md:grid-cols-[12rem_1fr]">
          {CURRENT_KEYS.filter((key) => data.current[key]).map((key) => (
            <div key={key} className="contents">
              <dt className="text-neutral-400">{key}</dt>
              <dd>
                <Metric termId="dev_log" icon={false}>
                  {data.current[key]}
                </Metric>
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="milestones-heading" className="space-y-3">
        <h2 id="milestones-heading" className="text-lg font-medium">
          Phase <span data-identifier="">0</span> milestones{" "}
          <span className="text-sm font-normal text-neutral-400">
            <Metric termId="milestone_status" zh>
              {done} of {data.milestones.length} done
            </Metric>
          </span>
        </h2>
        <ul className="space-y-2" aria-label="Milestones">
          {data.milestones.map((m) => {
            const [label, tone] = STATUS[m.status] ?? STATUS.not_started;
            const share = m.total ? (m.done / m.total) * 100 : m.status === "done" ? 100 : 0;
            return (
              <li key={m.id} className="space-y-1" data-milestone={m.id} data-status={m.status}>
                <div className="flex flex-wrap items-baseline gap-x-3 text-sm">
                  <span data-identifier="" className="w-12 font-medium">
                    {m.id}
                  </span>
                  <span data-identifier="" className="min-w-0 flex-1">
                    {m.title}
                  </span>
                  <Metric termId="milestone_status" icon={false}>
                    <span className="inline-flex items-center gap-1 text-xs text-neutral-400">
                      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${tone}`} />
                      {label}
                      {m.total ? ` · ${m.done}/${m.total} checks` : ""}
                    </span>
                  </Metric>
                </div>
                <div className="h-1.5 rounded bg-neutral-800" aria-hidden="true">
                  <div className={`h-1.5 rounded ${tone}`} style={{ width: `${share}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="decisions-heading" className="space-y-2">
        <h2 id="decisions-heading" className="text-lg font-medium">
          <Metric termId="open_decision" zh>
            Open decisions
          </Metric>
        </h2>
        <ul className="space-y-2 text-sm" aria-label="Open decisions">
          {data.open_decisions.map((d) => (
            <li key={d.id} className="flex flex-wrap gap-x-3">
              <span data-identifier="" className="w-12 font-medium">
                {d.id}
              </span>
              <span className="min-w-0 flex-1">
                <Metric termId="open_decision" icon={false}>
                  {d.decision}
                </Metric>
              </span>
              <span className="text-xs text-neutral-400">
                needed:{" "}
                <Metric termId="open_decision" icon={false}>
                  {d.needed_by}
                </Metric>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="phases-heading" className="space-y-2">
        <h2 id="phases-heading" className="text-lg font-medium">
          Later phases
        </h2>
        <ul className="space-y-2 text-sm" aria-label="Phases">
          {data.phases.map((p) => (
            <li key={p.number} className="flex flex-wrap gap-x-3">
              <span data-identifier="" className="w-16 font-medium">
                Phase {p.number}
              </span>
              <span className="min-w-0 flex-1 text-neutral-300">
                <Metric termId="page_progress" icon={false}>
                  {p.scope}
                </Metric>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="log-heading" className="space-y-2">
        <h2 id="log-heading" className="text-lg font-medium">
          <Metric termId="dev_log" zh>
            Development log
          </Metric>
        </h2>
        <ul className="space-y-2 text-sm" aria-label="Development log">
          {data.log.map((entry) => (
            <li key={`${entry.date}-${entry.milestone}`} className="flex flex-wrap gap-x-3">
              <Metric termId="as_of" icon={false} className="w-24 text-neutral-400">
                {entry.date}
              </Metric>
              <span data-identifier="" className="w-16 font-medium">
                {entry.milestone}
              </span>
              <span className="min-w-0 flex-1">
                <Metric termId="dev_log" icon={false}>
                  {entry.result}
                </Metric>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
