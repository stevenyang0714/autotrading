import type { Metadata } from "next";

import { ProgressView } from "@/components/progress/ProgressView";
import { loadProgress } from "@/lib/api";

// Re-read the documents on every request: edits show without a rebuild.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Build Progress" };

export default async function ProgressPage() {
  return <ProgressView data={await loadProgress()} />;
}
