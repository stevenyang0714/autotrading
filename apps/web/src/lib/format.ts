/**
 * Display formats for reported values (M0.5b). The exact reported value goes into a title so
 * nothing is lost to rounding; units follow the SEC unit keys (USD, USD/shares, shares).
 */

function scaled(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(3)}T`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(3)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(3)}M`;
  return value.toLocaleString("en-US");
}

function withDollar(text: string): string {
  return text.startsWith("-") ? `-$${text.slice(1)}` : `$${text}`;
}

/** "$416.161B", "-$147.782B", "$7.46", "15.005B shares". */
export function formatReported(value: string, unit: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  switch (unit) {
    case "USD":
      return withDollar(scaled(number));
    case "USD/shares":
      return withDollar(
        number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 }),
      );
    case "shares":
      return `${scaled(number)} shares`;
    default:
      return `${scaled(number)} ${unit}`;
  }
}

/** "416,161,000,000 USD": the value exactly as reported. */
export function exactReported(value: string, unit: string): string {
  const [whole, fraction] = value.replace(/^-/, "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const sign = value.startsWith("-") ? "-" : "";
  return `${sign}${grouped}${fraction ? `.${fraction}` : ""} ${unit}`;
}

/** "159,526" or "4.33": a reported value with thousands separators, every digit kept. */
export function groupDigits(value: string): string {
  return exactReported(value, "").trimEnd();
}

/** "$774.74": a market price, two decimals (the exact value goes into a title). */
export function formatPrice(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return withDollar(number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
}

/** "+0.66%", "-0.19%": a change in percent with its sign. */
export function formatChange(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

/** "NT$2,420.00", "$774.74": a price in its currency, two decimals (M3.7). */
export function formatMoney(value: string, currency: string): string {
  if (currency !== "TWD") return formatPrice(value);
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const text = Math.abs(number).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${number < 0 ? "-" : ""}NT$${text}`;
}

/** "NT$65.516B": a large amount in its currency. */
export function formatAmount(value: string, currency: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const prefix = currency === "TWD" ? "NT$" : "$";
  const abs = Math.abs(number);
  const text =
    abs >= 1e12
      ? `${(abs / 1e12).toFixed(3)}T`
      : abs >= 1e9
        ? `${(abs / 1e9).toFixed(3)}B`
        : abs >= 1e6
          ? `${(abs / 1e6).toFixed(3)}M`
          : abs.toLocaleString("en-US");
  return `${number < 0 ? "-" : ""}${prefix}${text}`;
}

/** "+15.00", "-0.40": a change in price units with its sign. */
export function formatSigned(value: string, digits = 2): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
}
