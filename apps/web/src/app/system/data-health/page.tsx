import type { Metadata } from "next";

import { DataHealthView } from "@/components/data-health/DataHealthView";
import { loadDataHealth } from "@/lib/api";

// Always read live status; never serve a cached page.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Data Health" };

export default async function DataHealthPage() {
  return <DataHealthView data={await loadDataHealth()} />;
}
