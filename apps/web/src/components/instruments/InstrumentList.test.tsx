import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedInstruments } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { InstrumentList } from "./InstrumentList";

describe("InstrumentList", () => {
  it("links every recorded stock to its page", () => {
    const { container } = render(<InstrumentList data={recordedInstruments} />);
    const links = within(screen.getByRole("list", { name: "Instruments" }))
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href")?.startsWith("/instruments/"));
    expect(links.map((link) => link.textContent)).toEqual(["AAPL", "XOM"]);
    expect(container.textContent).toContain("Exxon Mobil Corp");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("shows Data unavailable without numbers when the API is down", () => {
    const { container } = render(<InstrumentList data={null} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    expect(container.textContent).not.toMatch(/\d/);
  });
});
