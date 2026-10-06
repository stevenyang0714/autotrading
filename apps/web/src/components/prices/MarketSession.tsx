import { Metric } from "@/components/Metric";
import type { MarketState } from "@/lib/api";
import { formatSgtEt } from "@/lib/time";

/** "US market open" or "US market closed · opens <SGT · ET>" (glossary market_session). */
export function MarketSession({ market }: { market: MarketState }) {
  return (
    <span className="text-xs text-neutral-400" data-market-open={market.open}>
      <Metric termId="market_session" icon={false} zh>
        {market.open ? "US market open" : "US market closed"}
      </Metric>
      {market.open ? null : (
        <>
          {" · opens "}
          <Metric termId="market_session" icon={false}>
            {formatSgtEt(market.next_open)}
          </Metric>
        </>
      )}
    </span>
  );
}
