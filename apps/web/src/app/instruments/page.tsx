import type { Metadata } from "next";

import { InstrumentList } from "@/components/instruments/InstrumentList";
import { TaiwanList } from "@/components/taiwan/TaiwanList";
import { loadInstruments, loadLatestPrices, loadSourceHealth, loadTaiwan } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Instruments" };

export default async function InstrumentsPage() {
  const [data, prices, sources, taiwan] = await Promise.all([
    loadInstruments(),
    loadLatestPrices(),
    loadSourceHealth(),
    loadTaiwan(),
  ]);
  return (
    <div className="space-y-10">
      <InstrumentList
        data={data}
        prices={prices}
        sources={sources}
        otherStatuses={(taiwan?.rows ?? []).map((row) => (row.feed_status === "fixture" ? "fixture" : null))}
      />
      <TaiwanList data={taiwan} sources={sources} />
    </div>
  );
}
