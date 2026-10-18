/**
 * Labels for S4 momentum (M3.0, ADR-036 D7): every reason has its glossary term. Pure.
 */
import type { CompleteTermId } from "@/generated/glossary";

export const MOMENTUM_REASONS: Record<string, { label: string; termId: CompleteTermId }> = {
  month_start: { label: "Monthly target", termId: "momentum_target" },
  carried: { label: "Carried within the month", termId: "momentum_target" },
  unavailable: { label: "Unavailable", termId: "medium_term_momentum" },
};
