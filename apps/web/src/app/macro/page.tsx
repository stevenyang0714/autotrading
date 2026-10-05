import type { Metadata } from "next";

import { MacroList } from "@/components/macro/MacroList";
import { loadMacroSeries } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Macro" };

export default async function MacroPage() {
  return <MacroList data={await loadMacroSeries()} />;
}
