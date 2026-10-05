"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Metric } from "@/components/Metric";
import type { CompleteTermId } from "@/generated/glossary";
import { DASHBOARDS, SYSTEM_PAGES, dashboardHref } from "@/lib/dashboards";

interface NavItem {
  key: string;
  href: string;
  label: string;
  termId: CompleteTermId;
}

/** Left navigation. Collapses behind a Menu button below the md breakpoint. Each label shows
 * its glossary tooltip on hover or keyboard focus (errata E13; no "?" icon in the nav). */
export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const groups: [string, NavItem[]][] = [
    [
      "Dashboards",
      DASHBOARDS.filter((d) => d.group === "dashboards").map((d) => ({
        key: d.id,
        href: dashboardHref(d),
        label: d.label,
        termId: d.termId,
      })),
    ],
    [
      "System",
      SYSTEM_PAGES.map((p) => ({ key: p.id, href: p.href, label: p.label, termId: p.termId })),
    ],
  ];

  return (
    <nav aria-label="Main" className="p-4">
      <div className="flex items-center justify-between md:block">
        <Link href="/" className="font-semibold">
          Market Intelligence
        </Link>
        <button
          type="button"
          className="rounded border border-neutral-300 px-3 py-1 text-sm md:hidden dark:border-neutral-700"
          aria-expanded={open}
          aria-controls="dashboard-nav"
          onClick={() => setOpen((value) => !value)}
        >
          Menu
        </button>
      </div>
      <div id="dashboard-nav" className={`${open ? "block" : "hidden"} mt-4 space-y-6 md:block`}>
        {groups.map(([title, items]) => (
          <div key={title}>
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
              {title}
            </h2>
            <ul className="space-y-1" aria-label={title}>
              {items.map((item) => {
                const active = pathname === item.href;
                return (
                  <li key={item.key}>
                    <Metric termId={item.termId} icon={false} placement="right" className="w-full">
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        onClick={() => setOpen(false)}
                        className={`block rounded px-2 py-1 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-800 ${
                          active ? "bg-neutral-100 font-medium dark:bg-neutral-800" : ""
                        }`}
                      >
                        {item.label}
                      </Link>
                    </Metric>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
