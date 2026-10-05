"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { DASHBOARDS, dashboardHref } from "@/lib/dashboards";

/** Left navigation. Collapses behind a Menu button below the md breakpoint. */
export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

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
      <div id="dashboard-nav" className={`${open ? "block" : "hidden"} mt-4 md:block`}>
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
          Dashboards
        </h2>
        <ul className="space-y-1">
          {DASHBOARDS.filter((dashboard) => dashboard.group === "dashboards").map((dashboard) => {
            const href = dashboardHref(dashboard);
            const active = pathname === href;
            return (
              <li key={dashboard.id}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  className={`block rounded px-2 py-1 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-800 ${
                    active ? "bg-neutral-100 font-medium dark:bg-neutral-800" : ""
                  }`}
                >
                  {dashboard.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
