import type { Metadata } from "next";

import { KIND_CHOICES, NewsView } from "@/components/news/NewsView";
import { loadInstruments, loadNews, loadSourceHealth, type NewsKind } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "News" };

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

export default async function NewsPage({ searchParams }: PageProps<"/news">) {
  const query = await searchParams;
  const ticker = one(query.ticker)?.toUpperCase();
  const source = one(query.source);
  const kindParam = one(query.kind);
  const kind = KIND_CHOICES.some(([value]) => value && value === kindParam) ? (kindParam as NewsKind) : undefined;
  const tier = Number(one(query.tier));
  const maxTier = tier >= 1 && tier <= 4 ? tier : undefined;
  const knownOn = one(query.known_on);
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const [data, sources, instruments] = await Promise.all([
    loadNews({ ticker, source, maxTier, kinds: kind ? [kind] : undefined, knownAt: knownAt ?? undefined }),
    loadSourceHealth(),
    loadInstruments(),
  ]);
  return (
    <NewsView
      data={data}
      sources={sources}
      tickers={(instruments?.instruments ?? []).map((i) => i.ticker)}
      selection={{
        ticker,
        source,
        maxTier,
        kind,
        knownOn: knownAt ? knownOn : undefined,
        invalidKnownOn: Boolean(knownOn) && knownAt === null,
      }}
    />
  );
}
