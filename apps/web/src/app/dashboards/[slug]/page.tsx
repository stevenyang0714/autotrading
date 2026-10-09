import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PlannedPanel } from "@/components/PlannedPanel";
import { DASHBOARDS, findDashboard } from "@/lib/dashboards";

export const dynamicParams = false;

// Live dashboards have their own route; this one serves the planned ones.
export function generateStaticParams() {
  return DASHBOARDS.filter((dashboard) => !dashboard.live).map((dashboard) => ({
    slug: dashboard.slug,
  }));
}

export async function generateMetadata({
  params,
}: PageProps<"/dashboards/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  return { title: findDashboard(slug)?.label };
}

export default async function DashboardPage({ params }: PageProps<"/dashboards/[slug]">) {
  const { slug } = await params;
  const dashboard = findDashboard(slug);
  if (!dashboard || dashboard.live) notFound();
  return <PlannedPanel dashboard={dashboard} />;
}
