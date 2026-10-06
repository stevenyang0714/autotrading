import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recordedNews, recordedSources } from "@/test/fixtures";
import { unexplainedNumbers } from "@/test/numbers";

import { InstrumentNews } from "./InstrumentNews";
import { NewsView } from "./NewsView";

describe("NewsView (recorded GDELT and feeds)", () => {
  it("lists stories whose headlines link to the original articles", () => {
    const { container } = render(
      <NewsView data={recordedNews.all} sources={recordedSources} tickers={["AAPL", "NVDA"]} selection={{}} />,
    );
    const stories = within(screen.getByRole("list", { name: "News stories" })).getAllByRole("listitem");
    expect(stories.length).toBe(recordedNews.all.groups.length);
    const lead = recordedNews.all.groups[0].lead;
    expect(screen.getByRole("link", { name: lead.title })).toHaveProperty("href", lead.url);
    expect(container.textContent).toContain("News discovery via the GDELT Project");
    expect(unexplainedNumbers(container)).toEqual([]);
  });

  it("collapses copies of one story and counts stories, not articles", () => {
    const { container } = render(
      <NewsView data={recordedNews.nvda} sources={recordedSources} tickers={["NVDA"]} selection={{ ticker: "NVDA" }} />,
    );
    const syndicated = recordedNews.nvda.groups.find((g) => g.article_count > 1);
    expect(syndicated).toBeDefined();
    const row = container.querySelector(`[data-group="${syndicated!.group_id}"]`);
    expect(row?.textContent).toContain(`${syndicated!.article_count} copies on ${syndicated!.publisher_count} sites`);
    expect(row?.querySelectorAll("details li")).toHaveLength(syndicated!.others.length);
    expect(container.textContent).toContain(`${recordedNews.nvda.story_count} stories`);
    expect(recordedNews.nvda.story_count).toBeLessThan(recordedNews.nvda.article_count);
  });

  it("shows Data unavailable without numbers when the API is down", () => {
    const { container } = render(<NewsView data={null} sources={null} tickers={[]} selection={{}} />);
    expect(screen.getByRole("alert").textContent).toContain("Data unavailable");
    expect(container.querySelector('[aria-label="News stories"]')).toBeNull();
  });

  it("the instrument page section links to the company's news", () => {
    const { container } = render(
      <InstrumentNews ticker="NVDA" announcements={recordedNews.nvdaAnnouncements} coverage={recordedNews.nvdaCoverage} />,
    );
    expect(screen.getByText("Media coverage")).toBeTruthy();
    expect(screen.getByText("Company announcements")).toBeTruthy();
    expect(screen.getByRole("link", { name: /all NVDA news/ })).toHaveProperty("href", expect.stringContaining("/news?ticker=NVDA"));
    expect(unexplainedNumbers(container)).toEqual([]);
  });
});
