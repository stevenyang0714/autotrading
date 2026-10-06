import Link from "next/link";
import { Fragment } from "react";

import { Metric } from "@/components/Metric";
import type { AuditEntry, AuditLogPage, AuditQuery } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

const ACTION_TONE: Record<string, string> = {
  insert: "border-emerald-600/70 text-emerald-300",
  update: "border-sky-600/70 text-sky-300",
  delete: "border-red-600/70 text-red-300",
  supersede: "border-amber-600/70 text-amber-300",
};

/** A stored value exactly as recorded (JSON), shown as code: raw data, not a metric of ours. */
function Raw({ value }: { value: unknown }) {
  const text = value === null || value === undefined ? "null" : typeof value === "string" ? value : JSON.stringify(value);
  return (
    <code data-identifier="" className="break-all rounded bg-neutral-900 px-1 text-[12px]">
      {text}
    </code>
  );
}

function ActionBadge({ action }: { action: string }) {
  return (
    <Metric termId="audit_action" icon={false}>
      <span
        data-action={action}
        className={`inline-block rounded border px-1.5 py-0.5 text-[11px] leading-none ${ACTION_TONE[action] ?? "border-neutral-600"}`}
      >
        {action}
      </span>
    </Metric>
  );
}

function Hash({ value }: { value: string | null }) {
  if (!value) return <span className="text-neutral-600">–</span>;
  return (
    <code data-identifier="" title={value} className="text-[11px] text-neutral-500">
      {value.slice(0, 10)}…
    </code>
  );
}

function ObjectName({ entry }: { entry: AuditEntry }) {
  return (
    <span className="space-x-1">
      <span data-identifier="">{entry.table}</span>
      <span className="text-neutral-600">/</span>
      <Link
        href={`/system/audit-log?table=${encodeURIComponent(entry.table)}&object_id=${encodeURIComponent(entry.object_id)}`}
        data-identifier=""
        title={entry.object_id}
        className="underline-offset-2 hover:underline"
      >
        {entry.object_label ?? entry.object_id}
      </Link>
    </span>
  );
}

/** Bookkeeping fields every update touches; listed last and muted. */
const BOOKKEEPING = new Set(["updated_at", "version"]);

function Details({ entry }: { entry: AuditEntry }) {
  if (entry.changes.length === 0 && !entry.removed) return null;
  const changes = [
    ...entry.changes.filter((c) => !BOOKKEEPING.has(c.field)),
    ...entry.changes.filter((c) => BOOKKEEPING.has(c.field)),
  ];
  return (
    <details className="text-xs text-neutral-400">
      <summary className="cursor-pointer select-none">
        {entry.removed ? "Removed row" : `Changed fields`}
      </summary>
      <dl className="mt-1 space-y-1 pl-2">
        {changes.map((change) => (
          <div
            key={change.field}
            className={`flex flex-wrap items-baseline gap-x-2 ${BOOKKEEPING.has(change.field) ? "opacity-60" : ""}`}
          >
            <dt data-identifier="" className="text-neutral-300">
              {change.field}
            </dt>
            <dd className="flex flex-wrap items-baseline gap-x-1">
              <Raw value={change.old} /> <span aria-hidden="true">→</span> <Raw value={change.new} />
            </dd>
          </div>
        ))}
        {entry.removed
          ? Object.entries(entry.removed).map(([field, value]) => (
              <div key={field} className="flex flex-wrap items-baseline gap-x-2">
                <dt data-identifier="" className="text-neutral-300">
                  {field}
                </dt>
                <dd>
                  <Raw value={value} />
                </dd>
              </div>
            ))
          : null}
      </dl>
      <p className="mt-1 pl-2">
        before <Hash value={entry.before_hash} /> after <Hash value={entry.after_hash} />
      </p>
    </details>
  );
}

function When({ entry }: { entry: AuditEntry }) {
  return (
    <Metric termId="page_audit_log" icon={false}>
      {formatSgtEt(entry.occurred_at)}
    </Metric>
  );
}

function Actor({ entry }: { entry: AuditEntry }) {
  return (
    <Metric termId="audit_actor" icon={false}>
      <span data-identifier="">{entry.actor}</span>
    </Metric>
  );
}

function hrefWith(query: AuditQuery, extra: Partial<Record<string, string>>): string {
  const params = new URLSearchParams();
  const values: Record<string, string | undefined> = {
    table: query.table,
    action: query.action,
    actor: query.actor,
    object_id: query.objectId,
    since: query.since?.slice(0, 10),
    until: query.until?.slice(0, 10),
    ...extra,
  };
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value);
  const text = params.toString();
  return text ? `/system/audit-log?${text}` : "/system/audit-log";
}

/**
 * Audit log viewer (M0.9, ADR-019): the triggers' record of every change to registries and facts,
 * newest first, read-only. One GET form for the filters; "Older" pages by entry id. Stored values
 * are shown as code, exactly as recorded.
 */
export function AuditLogView({ data, query }: { data: AuditLogPage | null; query: AuditQuery }) {
  const facets = data?.facets;
  return (
    <section className="space-y-6">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_audit_log" zh>
            Audit Log
          </Metric>
        </h1>
        <form method="get" action="/system/audit-log" aria-label="Audit filters" className="flex flex-wrap items-center gap-2 text-sm">
          <span data-identifier="">
            <select name="table" defaultValue={query.table ?? ""} aria-label="Table" className="rounded border border-neutral-700 bg-transparent px-2 py-1">
              <option value="">All tables</option>
              {(facets?.tables ?? []).map((f) => (
                <option key={f.value} value={f.value}>
                  {f.value} ({f.count})
                </option>
              ))}
            </select>
          </span>
          <Metric termId="audit_action" icon={false}>
            <select name="action" defaultValue={query.action ?? ""} aria-label="Action" className="rounded border border-neutral-700 bg-transparent px-2 py-1">
              <option value="">All actions</option>
              {(facets?.actions ?? []).map((f) => (
                <option key={f.value} value={f.value}>
                  {f.value} ({f.count})
                </option>
              ))}
            </select>
          </Metric>
          <Metric termId="audit_actor" icon={false}>
            <select name="actor" defaultValue={query.actor ?? ""} aria-label="Actor" className="rounded border border-neutral-700 bg-transparent px-2 py-1">
              <option value="">All actors</option>
              {(facets?.actors ?? []).map((f) => (
                <option key={f.value} value={f.value}>
                  {f.value} ({f.count})
                </option>
              ))}
            </select>
          </Metric>
          {query.objectId ? <input type="hidden" name="object_id" value={query.objectId} /> : null}
          <label className="flex items-center gap-1 text-neutral-400">
            from
            <input type="date" name="since" defaultValue={query.since?.slice(0, 10) ?? ""} className="rounded border border-neutral-700 bg-transparent px-2 py-1" />
          </label>
          <label className="flex items-center gap-1 text-neutral-400">
            to
            <input type="date" name="until" defaultValue={query.until?.slice(0, 10) ?? ""} className="rounded border border-neutral-700 bg-transparent px-2 py-1" />
          </label>
          <button type="submit" className="rounded border border-neutral-700 px-3 py-1 hover:bg-neutral-800">
            Show
          </button>
          <Link href="/system/audit-log" className="text-neutral-400 underline-offset-2 hover:underline">
            Reset
          </Link>
        </form>
        {query.objectId ? (
          <p className="text-sm text-neutral-400">
            History of <code data-identifier="">{query.objectId}</code>
          </p>
        ) : null}
        {data ? (
          <p className="text-sm text-neutral-400">
            <Metric termId="page_audit_log" icon={false}>
              {data.matching} changes
            </Metric>{" "}
            match; newest first. Values are shown exactly as stored.
          </p>
        ) : null}
      </header>

      {data === null ? (
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no changes are shown.</p>
        </div>
      ) : data.entries.length === 0 ? (
        <p className="text-sm text-neutral-500">No changes match these filters.</p>
      ) : (
        <>
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-left text-sm" aria-label="Audit entries">
              <thead className="text-xs text-neutral-400">
                <tr>
                  <th className="py-2 pr-4 font-medium">When</th>
                  <th className="py-2 pr-4 font-medium">
                    <Metric termId="audit_action">Action</Metric>
                  </th>
                  <th className="py-2 pr-4 font-medium">Object</th>
                  <th className="py-2 pr-4 font-medium">
                    <Metric termId="audit_actor">Actor</Metric>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <Fragment key={entry.id}>
                    <tr data-entry={entry.id} className="border-t border-neutral-800 align-top">
                      <td className="whitespace-nowrap py-2 pr-4 text-neutral-400">
                        <When entry={entry} />
                      </td>
                      <td className="py-2 pr-4">
                        <ActionBadge action={entry.action} />
                      </td>
                      <td className="py-2 pr-4">
                        <ObjectName entry={entry} />
                      </td>
                      <td className="py-2 pr-4">
                        <Actor entry={entry} />
                      </td>
                    </tr>
                    {entry.changes.length || entry.removed ? (
                      <tr>
                        <td colSpan={4} className="pb-2 pl-4">
                          <Details entry={entry} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="space-y-3 lg:hidden" aria-label="Audit entries">
            {data.entries.map((entry) => (
              <li key={entry.id} data-entry={entry.id} className="space-y-1 rounded border border-neutral-800 p-3 text-sm">
                <p className="flex flex-wrap items-center gap-2">
                  <ActionBadge action={entry.action} />
                  <ObjectName entry={entry} />
                </p>
                <p className="flex flex-wrap gap-x-3 text-xs text-neutral-400">
                  <When entry={entry} />
                  <Actor entry={entry} />
                </p>
                <Details entry={entry} />
              </li>
            ))}
          </ul>
          <nav aria-label="Audit pages" className="flex gap-4 text-sm">
            {query.beforeId ? (
              <Link href={hrefWith(query, {})} className="underline-offset-2 hover:underline">
                Newest
              </Link>
            ) : null}
            {data.next_before_id ? (
              <Link
                href={hrefWith(query, { before_id: String(data.next_before_id) })}
                className="underline-offset-2 hover:underline"
              >
                Older
              </Link>
            ) : null}
          </nav>
        </>
      )}
    </section>
  );
}
