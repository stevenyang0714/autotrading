import type { Metadata } from "next";

import { ReconciliationView } from "@/components/reconciliation/ReconciliationView";
import { type ReconciliationQuery, loadReconciliations } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Reconciliation" };

const STATUSES = ["pass", "warn", "fail"] as const;
const FORMS = ["10-K", "10-Q"] as const;

export default async function ReconciliationPage({
  searchParams,
}: PageProps<"/system/reconciliation">) {
  const params = await searchParams;
  const query: ReconciliationQuery = {
    status: STATUSES.find((s) => s === params.status),
    form: FORMS.find((f) => f === params.form),
  };
  return <ReconciliationView data={await loadReconciliations(query)} query={query} />;
}
