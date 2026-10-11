import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedEvidence, recordedJournalCard, recordedSignals } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { EntryForm, evidenceKey } from "./EntryForm";

const action = async () => ({ errors: [] });

describe("EntryForm with recorded candidates", () => {
  it("groups the rows a card can cite and counts the selection", () => {
    render(
      <EntryForm
        ticker="AAPL"
        candidates={recordedEvidence.candidates}
        signals={recordedSignals.current}
        action={action}
      />,
    );
    for (const name of ["Reported values", "Filings", "Buyback statements", "Buyback state", "News", "Last close"]) {
      expect(screen.getByRole("list", { name })).toBeTruthy();
    }
    expect(screen.getByText(/0 selected; pick 3 to 7/)).toBeTruthy();
    const boxes = screen.getAllByRole<HTMLInputElement>("checkbox").filter((box) => box.name === "evidence");
    fireEvent.click(boxes[0]);
    expect(screen.getByText(/1 selected/)).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Why it matters (optional)" })).toBeTruthy();
    expect(JSON.parse(boxes[0].value)).toHaveProperty("kind");
  });

  it("switches between NO TRADE and paper TRADE fields", () => {
    render(<EntryForm ticker="AAPL" candidates={recordedEvidence.candidates} signals={[]} action={action} />);
    expect(screen.getByRole("combobox", { name: "Reason" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Paper TRADE/ }));
    expect(screen.getByRole("spinbutton", { name: "Shares" })).toBeTruthy();
    expect(screen.queryByRole("spinbutton", { name: /Limit price/ })).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "Order type" }), {
      target: { value: "limit" },
    });
    expect(screen.getByRole("spinbutton", { name: /Limit price/ })).toBeTruthy();
  });

  it("a new version starts from the card, its evidence checked, and has no decision", () => {
    const card = recordedJournalCard.card;
    render(
      <EntryForm ticker="AAPL" candidates={recordedEvidence.candidates} signals={[]} card={card} action={action} />,
    );
    expect(screen.getByText(/5 selected/)).toBeTruthy();
    const checked = screen
      .getAllByRole<HTMLInputElement>("checkbox")
      .filter((box) => box.checked)
      .map((box) => JSON.parse(box.value) as { kind: string; id?: string; day?: string });
    expect(checked.map((ref) => `${ref.kind}:${ref.id ?? ref.day}`).sort()).toEqual(
      card.evidence.map(evidenceKey).sort(),
    );
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("renders no unexplained number", () => {
    const { container } = render(
      <EntryForm
        ticker="AAPL"
        candidates={recordedEvidence.candidates}
        signals={recordedSignals.current}
        action={action}
      />,
    );
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
