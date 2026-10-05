import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("shows no numbers", () => {
    const { container } = render(<Home />);
    expect(container.textContent).toContain("Research broadly. Trade narrowly.");
    expect(container.textContent).not.toMatch(/\d/);
  });
});
