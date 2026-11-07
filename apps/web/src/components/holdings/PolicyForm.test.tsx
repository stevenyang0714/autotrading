import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { recordedPolicy } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { PolicyForm } from "./PolicyForm";

describe("PolicyForm", () => {
  it("starts empty for a first version: no target, band or member is filled in", () => {
    const { container } = render(<PolicyForm initial={null} next={1} action={vi.fn()} />);
    expect((screen.getByLabelText("Target (%)") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Band (± pp)") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Members") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Horizon (years)") as HTMLInputElement).value).toBe("");
    expect(container.querySelector("[data-total]")?.textContent).toContain("0.00%");
    expect(screen.getByRole("button", { name: /Save as version 1/ })).toBeTruthy();
  });

  it("starts from the version in force, adds and removes sleeves and adds up the targets", () => {
    const initial = recordedPolicy.policy?.content ?? null;
    const { container } = render(<PolicyForm initial={initial} next={3} action={vi.fn()} />);
    expect(container.querySelectorAll("[data-sleeve-row]")).toHaveLength(3);
    expect((container.querySelector('input[name="sleeve_0_members"]') as HTMLInputElement).value).toBe(
      "US:SPY=30, US:VOO=5, US:ZZZZ=5",
    );
    expect(container.querySelector("[data-total]")?.textContent).toContain("100.00%");
    fireEvent.click(screen.getByRole("button", { name: "Add a sleeve" }));
    expect(container.querySelectorAll("[data-sleeve-row]")).toHaveLength(4);
    fireEvent.change(container.querySelector('input[name="sleeve_3_target_pct"]') as HTMLInputElement, {
      target: { value: "5" },
    });
    expect(container.querySelector("[data-total]")?.textContent).toContain("105.00%");
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    expect(container.querySelectorAll("[data-sleeve-row]")).toHaveLength(3);
    expect((container.querySelector('input[name="sleeve_count"]') as HTMLInputElement).value).toBe("3");
    expect(container.querySelector("[data-total]")?.textContent).toContain("65.00%");
  });

  it("explains every number", () => {
    const { container } = render(<PolicyForm initial={recordedPolicy.policy?.content ?? null} next={3} action={vi.fn()} />);
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("has no order, broker or execution field", () => {
    const { container } = render(<PolicyForm initial={null} next={1} action={vi.fn()} />);
    const names = [...container.querySelectorAll("[name]")].map((el) => el.getAttribute("name"));
    expect(names.some((name) => /order|broker|route|execute/.test(name ?? ""))).toBe(false);
  });
});
