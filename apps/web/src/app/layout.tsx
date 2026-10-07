import type { Metadata } from "next";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Market Intelligence", template: "%s · Market Intelligence" },
  description: "Personal global market intelligence and paper-trading research platform.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased dark:bg-neutral-950 dark:text-neutral-100">
        <div className="min-h-screen md:flex">
          <aside className="border-b border-neutral-200 md:w-64 md:shrink-0 md:border-r md:border-b-0 dark:border-neutral-800">
            <Nav />
          </aside>
          <main className="min-w-0 flex-1 p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
