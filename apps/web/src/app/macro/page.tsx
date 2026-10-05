import type { Metadata } from "next";

import { MacroList } from "@/components/macro/MacroList";
import { loadMacroSeries, loadSourceHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Macro" };

export default async function MacroPage() {
  const [data, sources] = await Promise.all([loadMacroSeries(), loadSourceHealth()]);
  return <MacroList data={data} sources={sources} />;
}
