import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ReconciliationDetailView } from "@/components/reconciliation/ReconciliationView";
import { loadReconciliation } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: PageProps<"/system/reconciliation/[accession]">): Promise<Metadata> {
  const { accession } = await params;
  return { title: `Reconciliation ${accession}` };
}

export default async function ReconciliationFilingPage({
  params,
}: PageProps<"/system/reconciliation/[accession]">) {
  const { accession } = await params;
  const result = await loadReconciliation(decodeURIComponent(accession));
  if (result.status === "not_found") notFound();
  if (result.status === "unavailable") {
    return (
      <p role="alert" className="rounded border border-red-800 bg-red-950/40 px-3 py-2 text-sm">
        Data unavailable: the API could not be reached.
      </p>
    );
  }
  return <ReconciliationDetailView data={result.data} />;
}
