/**
 * Dashboard registry (02 §21). Order and labels are canonical.
 *
 * plannedPhase = first phase in which the dashboard shows real content
 * (mapping approved with the M0.1 plan; see docs/milestones/ROADMAP.md).
 * Until then the page renders "Planned — Phase N" and never placeholder numbers.
 * A built dashboard is marked `live` and has its own route (app/dashboards/<slug>/page.tsx).
 */

import type { CompleteTermId } from "@/generated/glossary";

export type PlannedPhase = 1 | 2 | 3 | 4 | 5 | 6;

/** "system" holds the Phase 0 screens added in M0.9 (Data Health, Instrument, Macro, News, Audit log). */
export type NavGroup = "dashboards" | "system";

export interface DashboardDef {
  id: string;
  slug: string;
  label: string;
  /** Glossary entry for the label (errata E13); must be a complete term or tsc fails. */
  termId: CompleteTermId;
  purpose: string;
  plannedPhase: PlannedPhase;
  group: NavGroup;
  /** Built: served by its own route instead of the Planned panel. */
  live?: true;
}

export const DASHBOARDS: readonly DashboardDef[] = [
  {
    id: "global_monitor",
    slug: "global-monitor",
    label: "Global Monitor",
    termId: "dashboard_global_monitor",
    purpose: "World map with macro, geopolitics, weather, shipping and commodity context.",
    plannedPhase: 3,
    group: "dashboards",
  },
  {
    id: "market_regime",
    slug: "market-regime",
    label: "Market Regime",
    termId: "dashboard_market_regime",
    purpose: "Growth, inflation, liquidity, credit, volatility and risk appetite.",
    plannedPhase: 2,
    group: "dashboards",
    live: true,
  },
  {
    id: "opportunity_radar",
    slug: "opportunity-radar",
    label: "Opportunity Radar",
    termId: "dashboard_opportunity_radar",
    purpose: "Candidates the rules flag, and every instrument's trend, risk, value and quality against its own history.",
    plannedPhase: 2,
    group: "dashboards",
    live: true,
  },
  {
    id: "fundamental_research",
    slug: "fundamental-research",
    label: "Fundamental Research",
    termId: "dashboard_fundamental_research",
    purpose: "Company economics: financials, valuation, quality and capital allocation.",
    plannedPhase: 1,
    group: "dashboards",
    live: true,
  },
  {
    id: "corporate_actions",
    slug: "corporate-actions",
    label: "Corporate Actions",
    termId: "dashboard_corporate_actions",
    purpose: "Buybacks, dividends, M&A, equity issuance, convertibles and insider activity.",
    plannedPhase: 1,
    group: "dashboards",
    live: true,
  },
  {
    id: "event_transmission",
    slug: "event-transmission",
    label: "Event Transmission",
    termId: "dashboard_event_transmission",
    purpose: "Causal graphs from events to commodities, industries and companies.",
    plannedPhase: 3,
    group: "dashboards",
  },
  {
    id: "earnings",
    slug: "earnings",
    label: "Earnings",
    termId: "dashboard_earnings",
    purpose: "Calendar, results against expectations, guidance, revisions and market reaction.",
    plannedPhase: 1,
    group: "dashboards",
    live: true,
  },
  {
    id: "x_expert_watch",
    slug: "x-expert-watch",
    label: "X / Expert Watch",
    termId: "dashboard_x_expert_watch",
    purpose: "Researcher watchlists, mentions and thesis changes.",
    plannedPhase: 4,
    group: "dashboards",
  },
  {
    id: "policy_monitor",
    slug: "policy-monitor",
    label: "Policy Monitor",
    termId: "dashboard_policy_monitor",
    purpose: "White House and agency actions, tariffs, sanctions and critical materials, by lifecycle state.",
    plannedPhase: 3,
    group: "dashboards",
  },
  {
    id: "congress_trades",
    slug: "congress-trades",
    label: "Congress Trades",
    termId: "dashboard_congress_trades",
    purpose: "Reported trades from House and Senate disclosures, with disclosure lag.",
    plannedPhase: 4,
    group: "dashboards",
  },
  {
    id: "options_vol",
    slug: "options-vol",
    label: "Options & Vol",
    termId: "dashboard_options_vol",
    purpose: "Implied volatility, skew, term structure and hedges.",
    plannedPhase: 5,
    group: "dashboards",
  },
  {
    id: "portfolio_risk",
    slug: "portfolio-risk",
    label: "Portfolio Risk",
    termId: "dashboard_portfolio_risk",
    purpose: "The paper portfolio's exposures, limits, drawdown and risk checks.",
    plannedPhase: 2,
    group: "dashboards",
    live: true,
  },
  {
    id: "alerts_center",
    slug: "alerts-center",
    label: "Alerts Center",
    termId: "dashboard_alerts_center",
    purpose: "Signal convergence alerts, rules and acknowledgement.",
    plannedPhase: 1,
    group: "dashboards",
    live: true,
  },
  {
    id: "strategy_lab",
    slug: "strategy-lab",
    label: "Strategy Lab",
    termId: "dashboard_strategy_lab",
    purpose: "Paper journal, signals, the ETF rotation, company momentum and walk-forward backtests with costs.",
    plannedPhase: 1,
    group: "dashboards",
    live: true,
  },
  {
    id: "execution",
    slug: "execution",
    label: "Execution",
    termId: "dashboard_execution",
    purpose: "Order preview, risk approval, broker status, fills and audit trail.",
    plannedPhase: 5,
    group: "dashboards",
  },
];

/** Live system pages (nav group "System"). Data Health was pulled forward from M0.9 to M0.4, Instruments to M0.5b, Macro to M0.6, News to M0.8; Audit Log is M0.9, Reconciliation M1.1. */
export interface SystemPageDef {
  id: string;
  href: string;
  label: string;
  termId: CompleteTermId;
}

export const SYSTEM_PAGES: readonly SystemPageDef[] = [
  {
    id: "today",
    href: "/",
    label: "Today",
    termId: "page_today",
  },
  {
    id: "holdings",
    href: "/holdings",
    label: "Holdings",
    termId: "page_holdings",
  },
  {
    id: "data_health",
    href: "/system/data-health",
    label: "Data Health",
    termId: "page_data_health",
  },
  {
    id: "instruments",
    href: "/instruments",
    label: "Instruments",
    termId: "page_instruments",
  },
  {
    id: "macro",
    href: "/macro",
    label: "Macro",
    termId: "page_macro",
  },
  {
    id: "news",
    href: "/news",
    label: "News",
    termId: "page_news",
  },
  {
    id: "audit_log",
    href: "/system/audit-log",
    label: "Audit Log",
    termId: "page_audit_log",
  },
  {
    id: "reconciliation",
    href: "/system/reconciliation",
    label: "Reconciliation",
    termId: "page_reconciliation",
  },
  {
    id: "progress",
    href: "/system/progress",
    label: "Build Progress",
    termId: "page_progress",
  },
];

export function findDashboard(slug: string): DashboardDef | undefined {
  return DASHBOARDS.find((dashboard) => dashboard.slug === slug);
}

export function dashboardHref(dashboard: DashboardDef): string {
  return `/dashboards/${dashboard.slug}`;
}

export function plannedLabel(phase: PlannedPhase): string {
  return `Planned — Phase ${phase}`;
}
