import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HoldingEntryForm } from "./HoldingEntryForm";

describe("HoldingEntryForm", () => {
  it("shows a trade's fields, then an amount and currency for cash kinds", () => {
    render(<HoldingEntryForm accounts={["Firstrade", "元大"]} today="2026-10-27" action={vi.fn()} />);
    expect(screen.getByLabelText("Shares")).toBeTruthy();
    expect(screen.getByLabelText("Price (USD)")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Market"), { target: { value: "TW" } });
    expect(screen.getByLabelText("Price (TWD)")).toBeTruthy();
    expect((screen.getByLabelText("Trade date") as HTMLInputElement).max).toBe("2026-10-27");
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "deposit" } });
    expect(screen.queryByLabelText("Shares")).toBeNull();
    expect(screen.queryByLabelText("Symbol")).toBeNull();
    expect(screen.getByLabelText("Currency")).toBeTruthy();
    expect(screen.getByLabelText("Amount")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "dividend" } });
    expect(screen.getByLabelText("Symbol")).toBeTruthy();
    expect(screen.getByLabelText("Amount (TWD)")).toBeTruthy();
  });

  it("has no order, broker or execution field", () => {
    const { container } = render(<HoldingEntryForm accounts={[]} today="2026-10-27" action={vi.fn()} />);
    const names = [...container.querySelectorAll("[name]")].map((el) => el.getAttribute("name"));
    expect(names.some((name) => /order|broker|route|execute/.test(name ?? ""))).toBe(false);
  });
});
