import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GLOSSARY } from "@/generated/glossary";

import { Metric } from "./Metric";

describe("Metric", () => {
  it("marks its value as a glossary-backed metric", () => {
    const { container } = render(<Metric termId="rate_limit">5/s</Metric>);
    const root = container.querySelector("[data-metric]");
    expect(root?.getAttribute("data-term-id")).toBe("rate_limit");
    expect(root?.textContent).toContain("5/s");
  });

  it("shows a compact tooltip on hover and hides it on leave", () => {
    render(<Metric termId="data_freshness">Fresh</Metric>);
    const value = screen.getByText("Fresh");
    fireEvent.mouseEnter(value);
    expect(screen.getByRole("tooltip").textContent).toContain(
      GLOSSARY.data_freshness.short_definition,
    );
    fireEvent.mouseLeave(value);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("shows the tooltip on keyboard focus and closes it with Escape", () => {
    render(<Metric termId="source_tier">Tier</Metric>);
    const button = screen.getByRole("button", { name: "What is Source Tier?" });
    fireEvent.focus(button);
    expect(button.getAttribute("aria-describedby")).toBe(screen.getByRole("tooltip").id);
    fireEvent.keyDown(button, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens the full entry on tap/click and closes it with Escape or outside click", () => {
    render(
      <div>
        <Metric termId="dead_letter">Dead letters</Metric>
        <p>outside</p>
      </div>,
    );
    const button = screen.getByRole("button", { name: "What is Dead Letter?" });
    fireEvent.click(button);
    const dialog = screen.getByRole("dialog", { name: "Dead Letter" });
    expect(dialog.textContent).toContain(GLOSSARY.dead_letter.full_definition);
    expect(dialog.querySelector("a")?.getAttribute("href")).toBe(GLOSSARY.dead_letter.source_url);
    expect(button.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(button);
    fireEvent.pointerDown(screen.getByText("outside"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("can render without the ? button (nav labels, dense values)", () => {
    render(<Metric termId="planned_phase" icon={false}>Planned</Metric>);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("glossary contract (compile time)", () => {
  it("rejects unknown and unfinished terms", () => {
    // Checked by `tsc` in CI: if Metric ever accepted these ids, the expect-error
    // directives below would become unused and type-checking would fail.
    // @ts-expect-error - not a glossary term
    const unknown = <Metric termId="not_a_glossary_term">x</Metric>;
    // @ts-expect-error - seed term, not complete: may not be rendered yet
    const seed = <Metric termId="thesis_score">x</Metric>;
    expect([unknown, seed]).toHaveLength(2);
  });
});
