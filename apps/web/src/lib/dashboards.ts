/**
 * Dashboard registry (02 §21). Order and labels are canonical.
 *
 * plannedPhase = first phase in which the dashboard shows real content
 * (mapping approved with the M0.1 plan; see docs/milestones/ROADMAP.md).
 * Until then the page renders "Planned — Phase N" and never placeholder numbers.
 */

export type PlannedPhase = 1 | 2 | 3 | 4 | 5 | 6;

/** "system" holds the Phase 0 screens added in M0.9 (Data Health, Instrument, Macro, News, Audit log). */
export type NavGroup = "dashboards" | "system";

export interface DashboardDef {
  id: string;
  slug: string;
  label: string;
  purpose: string;
  plannedPhase: PlannedPhase;
  group: NavGroup;
}

export const DASHBOARDS: readonly DashboardDef[] = [
  {
    id: "global_monitor",
    slug: "global-monitor",
    label: "Global Monitor",
    purpose: "World map with macro, geopolitics, weather, shipping and commodity context.",
    plannedPhase: 3,
    group: "dashboards",
  },
  {
    id: "market_regime",
    slug: "market-regime",
    label: "Market Regime",
    purpose: "Growth, inflation, liquidity, credit, volatility and risk appetite.",
    plannedPhase: 2,
    group: "dashboards",
  },
  {
    id: "opportunity_radar",
    slug: "opportunity-radar",
    label: "Opportunity Radar",
    purpose: "Long, short and hedge candidates with signal convergence.",
    plannedPhase: 2,
    group: "dashboards",
  },
  {
    id: "fundamental_research",
    slug: "fundamental-research",
    label: "Fundamental Research",
    purpose: "Company economics: financials, valuation, quality and capital allocation.",
    plannedPhase: 1,
    group: "dashboards",
  },
  {
    id: "corporate_actions",
    slug: "corporate-actions",
    label: "Corporate Actions",
    purpose: "Buybacks, dividends, M&A, equity issuance, convertibles and insider activity.",
    plannedPhase: 1,
    group: "dashboards",
  },
  {
    id: "event_transmission",
    slug: "event-transmission",
    label: "Event Transmission",
    purpose: "Causal graphs from events to commodities, industries and companies.",
    plannedPhase: 3,
    group: "dashboards",
  },
  {
    id: "earnings",
    slug: "earnings",
    label: "Earnings",
    purpose: "Calendar, results against expectations, guidance, revisions and market reaction.",
    plannedPhase: 1,
    group: "dashboards",
  },
  {
    id: "x_expert_watch",
    slug: "x-expert-watch",
    label: "X / Expert Watch",
    purpose: "Researcher watchlists, mentions and thesis changes.",
    plannedPhase: 4,
    group: "dashboards",
  },
  {
    id: "policy_monitor",
    slug: "policy-monitor",
    label: "Policy Monitor",
    purpose: "White House and agency actions, tariffs, sanctions and critical materials, by lifecycle state.",
    plannedPhase: 3,
    group: "dashboards",
  },
  {
    id: "congress_trades",
    slug: "congress-trades",
    label: "Congress Trades",
    purpose: "Reported trades from House and Senate disclosures, with disclosure lag.",
    plannedPhase: 4,
    group: "dashboards",
  },
  {
    id: "options_vol",
    slug: "options-vol",
    label: "Options & Vol",
    purpose: "Implied volatility, skew, term structure and hedges.",
    plannedPhase: 5,
    group: "dashboards",
  },
  {
    id: "portfolio_risk",
    slug: "portfolio-risk",
    label: "Portfolio Risk",
    purpose: "Exposure, stress, drawdown and hedges.",
    plannedPhase: 2,
    group: "dashboards",
  },
  {
    id: "alerts_center",
    slug: "alerts-center",
    label: "Alerts Center",
    purpose: "Signal convergence alerts, rules and acknowledgement.",
    plannedPhase: 1,
    group: "dashboards",
  },
  {
    id: "strategy_lab",
    slug: "strategy-lab",
    label: "Strategy Lab",
    purpose: "Paper journal, backtests, walk-forward validation and paper trading.",
    plannedPhase: 1,
    group: "dashboards",
  },
  {
    id: "execution",
    slug: "execution",
    label: "Execution",
    purpose: "Order preview, risk approval, broker status, fills and audit trail.",
    plannedPhase: 5,
    group: "dashboards",
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
