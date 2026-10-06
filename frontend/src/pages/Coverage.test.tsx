import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { freshness, groupSources } from "../lib/sources";
import { source } from "../test/fixtures";
import { mockFetch, renderPage, SIGNED_IN } from "../test/render";
import Coverage from "./Coverage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const SOURCES = [
  source({ key: "central", name: "Central Public Procurement Portal", open_tenders: 1825 }),
  source({ key: "ntpc", name: "NTPC", open_tenders: 300 }),
  source({ key: "mp", name: "Madhya Pradesh", state: "Madhya Pradesh", open_tenders: 900 }),
  source({ key: "cg", name: "Chhattisgarh", state: "Chhattisgarh", open_tenders: 400, last_success: null, last_run: { status: "failed", finished: "2026-10-06T07:00:00Z", new: 0, updated: 0 } }),
  source({ key: "jk", name: "Jammu and Kashmir", state: "Jammu and Kashmir", last_success: "2026-10-01T00:00:00Z" }),
];

describe("source grouping", () => {
  it("puts all-India portals first by size, then state portals alphabetically", () => {
    const g = groupSources(SOURCES);
    expect(g.central.map((s) => s.key)).toEqual(["central", "ntpc"]);
    expect(g.states.map((s) => s.key)).toEqual(["cg", "jk", "mp"]);
  });

  it("judges freshness by the last successful crawl, not the last run", () => {
    const now = new Date("2026-10-06T12:00:00Z").getTime();
    expect(freshness(SOURCES[0], now)).toBe("fresh");
    expect(freshness(SOURCES[3], now)).toBe("never");
    expect(freshness(SOURCES[4], now)).toBe("stale");
  });
});

describe("Coverage page", () => {
  it("lists central/PSU and state portals in their own groups", async () => {
    mockFetch({ "GET /api/auth/me": SIGNED_IN, "GET /api/config": {}, "GET /api/sources": SOURCES });
    renderPage(<Coverage />, "/coverage");

    const central = (await screen.findByRole("heading", { name: /Central government, PSUs and defence/ })).closest("section")!;
    const states = screen.getByRole("heading", { name: /States and union territories/ }).closest("section")!;
    expect(await within(central).findByText("NTPC")).toBeTruthy();
    expect(within(central).queryByText("Chhattisgarh")).toBeNull();
    expect(within(states).getByText("Madhya Pradesh", { selector: "span" })).toBeTruthy();
    expect(within(states).getAllByRole("link").map((a) => a.textContent?.trim())).toEqual(["Chhattisgarh", "Jammu and Kashmir", "Madhya Pradesh"]);
    // No award or bidder UI: that data is CAPTCHA-gated and not collected.
    expect(screen.queryByText(/bidders?\b/i)).toBeNull();
  });
});
