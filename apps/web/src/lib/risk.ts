/**
 * Labels and formats for the paper portfolio and risk checks (M2.3, ADR-031): every limit has
 * its glossary term. Pure.
 */
import type { CompleteTermId } from "@/generated/glossary";

export const LIMIT_TERMS: Record<string, CompleteTermId> = {
  price: "risk_limit_price",
  max_loss_stated: "max_loss",
  max_loss: "risk_limit_max_loss",
  position: "risk_limit_position",
  sector: "risk_limit_sector",
  volume: "risk_limit_volume",
  gross: "risk_limit_gross",
};

export const SECTOR_LABELS: Record<string, string> = {
  information_technology: "Information technology",
  communication_services: "Communication services",
  financials: "Financials",
  energy: "Energy",
  consumer_discretionary: "Consumer discretionary",
  broad_market: "Broad market",
  fixed_income: "Fixed income",
  commodity: "Commodity",
  unknown: "No sector",
};

export const TRIGGER_LABELS: Record<string, string> = {
  trade: "Journal TRADE",
  on_demand: "Tried",
  standard: "Standard position",
};

export function sectorLabel(sector: string | null | undefined): string {
  return sector ? (SECTOR_LABELS[sector] ?? sector) : "No sector";
}

/** "100,000.00 USD", "-4,000.00 USD". */
export function usd(value: string | number): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD`;
}

/** "10.00%". */
export function pct(value: string | number): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : String(value);
}

export function trim(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}
