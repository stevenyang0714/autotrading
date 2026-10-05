import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedProgress } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { ProgressView } from "./ProgressView";

describe("ProgressView", () => {
  it("lists milestones with their status and the open decisions", () => {
    const { container } = render(<ProgressView data={recordedProgress} />);
    const m01 = container.querySelector('[data-milestone="M0.1"]');
    expect(m01?.getAttribute("data-status")).toBe("done");
    expect(within(screen.getByRole("list", { name: "Open decisions" })).getAllByRole("listitem")[0].textContent).toContain(
      "OD-1",
    );
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows Data unavailable without numbers when the documents cannot be read", () => {
    const { container } = render(<ProgressView data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    expect(container.textContent).not.toMatch(/\d/);
  });
});
