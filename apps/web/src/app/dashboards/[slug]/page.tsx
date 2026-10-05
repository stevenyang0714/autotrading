import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PlannedPanel } from "@/components/PlannedPanel";
import { DASHBOARDS, findDashboard } from "@/lib/dashboards";

export const dynamicParams = false;

export function generateStaticParams() {
  return DASHBOARDS.map((dashboard) => ({ slug: dashboard.slug }));
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
  if (!dashboard) notFound();
  return <PlannedPanel dashboard={dashboard} />;
}
