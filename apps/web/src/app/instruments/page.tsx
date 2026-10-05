import type { Metadata } from "next";

import { InstrumentList } from "@/components/instruments/InstrumentList";
import { loadInstruments, loadSourceHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Instruments" };

export default async function InstrumentsPage() {
  const [data, sources] = await Promise.all([loadInstruments(), loadSourceHealth()]);
  return <InstrumentList data={data} sources={sources} />;
}
