/** Human labels for Data Health codes. The codes themselves are defined in the glossary. */

export type Tone = "good" | "warn" | "bad" | "muted";

export const FRESHNESS: Record<"fresh" | "stale" | "failing" | "disabled", [string, Tone]> = {
  fresh: ["Fresh", "good"],
  stale: ["Stale", "warn"],
  failing: ["Failing", "bad"],
  disabled: ["Not enabled", "muted"],
};

export const LICENSE: Record<string, string> = {
  public: "Public",
  licensed_personal: "Licensed (personal)",
  licensed_redistribution: "Licensed (redistribution)",
  restricted: "Restricted",
  unknown: "Unknown",
};

export const ACCESS: Record<string, [string, Tone]> = {
  active: ["Active", "good"],
  no_credentials: ["No credentials", "warn"],
  disabled: ["Disabled", "muted"],
  pending_review: ["Pending review", "muted"],
};

export const CADENCE: Record<string, string> = {
  intraday: "Intraday",
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  per_filing: "Per filing",
  per_release: "Per release",
};

export const RUN_STATUS: Record<string, [string, Tone]> = {
  queued: ["Queued", "muted"],
  running: ["Running", "muted"],
  succeeded: ["Succeeded", "good"],
  skipped: ["Skipped", "good"],
  failed: ["Failed", "warn"],
  dead_lettered: ["Dead-lettered", "bad"],
};

export const TONE_CLASS: Record<Tone, string> = {
  good: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
  muted: "bg-neutral-500",
};
