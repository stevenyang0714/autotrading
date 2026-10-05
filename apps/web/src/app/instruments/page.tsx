import type { Metadata } from "next";

import { InstrumentList } from "@/components/instruments/InstrumentList";
import { loadInstruments } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Instruments" };

export default async function InstrumentsPage() {
  return <InstrumentList data={await loadInstruments()} />;
}
