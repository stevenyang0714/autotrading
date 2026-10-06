import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedAudit } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { AuditLogView } from "./AuditLogView";

describe("AuditLogView (recorded audit log)", () => {
  it("lists changes newest first with actor, action and object", () => {
    const { container } = render(<AuditLogView data={recordedAudit.all} query={{}} />);
    const ids = [...container.querySelectorAll("tr[data-entry]")].map((row) => Number(row.getAttribute("data-entry")));
    expect(ids).toEqual([...ids].sort((a, b) => b - a));
    expect(container.textContent).toContain("config:sources.yaml");
    expect(container.textContent).toContain(`${recordedAudit.all.matching} changes`);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows each changed field old and new", () => {
    const { container } = render(
      <AuditLogView data={recordedAudit.sourceUpdates} query={{ table: "sources", action: "update" }} />,
    );
    const table = screen.getByRole("table", { name: "Audit entries" });
    const gdelt = within(table).getByText("GDELT DOC 2.0 API").closest("tr")!;
    const details = gdelt.nextElementSibling!;
    expect(details.textContent).toContain("priority");
    expect(details.textContent).toMatch(/40\s*→\s*99/);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("keeps a deleted row and names its object by id", () => {
    const { container } = render(<AuditLogView data={recordedAudit.deletes} query={{ action: "delete" }} />);
    expect(container.textContent).toContain("Removed row");
    expect(container.textContent).toContain("audit_probe");
    expect(container.querySelector('[data-action="delete"]')).not.toBeNull();
  });

  it("links to older entries when there are more", () => {
    const page = { ...recordedAudit.all, next_before_id: 42 };
    render(<AuditLogView data={page} query={{ table: "sources" }} />);
    expect(screen.getByRole("link", { name: "Older" }).getAttribute("href")).toBe(
      "/system/audit-log?table=sources&before_id=42",
    );
  });

  it("shows Data unavailable when the API is down", () => {
    render(<AuditLogView data={null} query={{}} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
  });
});
