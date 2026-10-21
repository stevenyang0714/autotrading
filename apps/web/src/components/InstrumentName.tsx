/**
 * A ticker's display name (M3.0c, ADR-038): "埃克森美孚（Exxon Mobil）" from
 * config/instrument_labels.yaml, next to the ticker. Names can hold digits ("標普 500 ETF"), so
 * they count as identifiers, not numbers.
 */
export function InstrumentName({ name, zh }: { name?: string | null; zh?: string | null }) {
  if (!name && !zh) return null;
  const text = zh && name && zh !== name ? `${zh}（${name}）` : (zh || name);
  return (
    <span data-identifier="" data-name="" className="text-xs text-neutral-400">
      {text}
    </span>
  );
}
