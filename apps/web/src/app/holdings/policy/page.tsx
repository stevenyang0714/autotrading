import type { Metadata } from "next";

import { savePolicyAction } from "@/app/holdings/policy/actions";
import { Metric } from "@/components/Metric";
import { PolicyForm } from "@/components/holdings/PolicyForm";
import { PolicyView } from "@/components/holdings/PolicyView";
import { loadPolicy, loadPolicyVersions } from "@/lib/api";
import { endOfDaySgt } from "@/lib/time";

// The policy is weighed against live holdings and closes: always read live, never cached.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Investment Policy" };

/** Steven's investment policy (M3.12, ADR-043): his versions, the drift and the trades. */
export default async function PolicyPage({ searchParams }: PageProps<"/holdings/policy">) {
  const query = await searchParams;
  const knownOn = typeof query.known_on === "string" && query.known_on ? query.known_on : undefined;
  const knownAt = knownOn ? endOfDaySgt(knownOn) : null;
  const [data, versions] = await Promise.all([loadPolicy(knownAt ?? undefined), loadPolicyVersions()]);
  if (data === null) {
    return (
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">
          <Metric termId="page_policy">Investment Policy</Metric>
        </h1>
        <div role="alert" className="rounded border border-amber-600/60 bg-amber-950/40 p-4 text-sm">
          <p className="font-medium">Data unavailable</p>
          <p className="mt-1 text-neutral-400">The API could not be reached, so no policy is shown.</p>
        </div>
      </section>
    );
  }
  const latest = versions?.versions[0] ?? null;
  return (
    <PolicyView
      data={data}
      versions={versions}
      knownOn={knownAt ? knownOn : undefined}
      invalidKnownOn={Boolean(knownOn) && knownAt === null}
      form={
        knownAt === null ? (
          <PolicyForm initial={latest?.content ?? null} next={(latest?.version ?? 0) + 1} action={savePolicyAction} />
        ) : undefined
      }
    />
  );
}
