import type { Metadata } from "next";

import { AuditLogView } from "@/components/audit/AuditLogView";
import { type AuditAction, type AuditQuery, loadAuditLog } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Audit Log" };

const ACTIONS: AuditAction[] = ["insert", "update", "delete", "supersede"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

export default async function AuditLogPage({ searchParams }: PageProps<"/system/audit-log">) {
  const params = await searchParams;
  const action = one(params.action);
  const since = one(params.since);
  const until = one(params.until);
  const before = Number(one(params.before_id));
  const query: AuditQuery = {
    table: one(params.table),
    action: ACTIONS.find((a) => a === action),
    actor: one(params.actor),
    objectId: one(params.object_id),
    // Dates are Singapore days (ADR-005): from the start of `since` to the end of `until`.
    since: since && DAY.test(since) ? `${since}T00:00:00+08:00` : undefined,
    until: until && DAY.test(until) ? `${until}T23:59:59+08:00` : undefined,
    beforeId: Number.isInteger(before) && before > 0 ? before : undefined,
  };
  return <AuditLogView data={await loadAuditLog(query)} query={query} />;
}
