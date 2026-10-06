import type { Metadata } from "next";

import { InstrumentList } from "@/components/instruments/InstrumentList";
import { loadInstruments, loadLatestPrices, loadSourceHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Instruments" };

export default async function InstrumentsPage() {
  const [data, prices, sources] = await Promise.all([
    loadInstruments(),
    loadLatestPrices(),
    loadSourceHealth(),
  ]);
  return <InstrumentList data={data} prices={prices} sources={sources} />;
}
