import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENDER } from "../test/fixtures";
import { mockFetch, renderPage, SIGNED_IN, SIGNED_OUT } from "../test/render";
import { RecommendedList, RecommendedSection } from "./Recommended";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const REASONS = ["Sector: Roads", "State: Chhattisgarh", "Within your turnover limit"];
const page = (over = {}) => ({ count: 1, next: null, previous: null, profile_incomplete: false, results: [{ ...TENDER, reasons: REASONS }], ...over });
const base = { "GET /api/config": {}, "GET /api/pipeline": [], "GET /api/sources": [] };

describe("Recommended for you", () => {
  it("shows each tender with the reasons it matched", async () => {
    mockFetch({ ...base, "GET /api/auth/me": SIGNED_IN, "GET /api/recommendations": page() });
    renderPage(<RecommendedSection />);

    expect(await screen.findByText("Resurfacing of NH-44")).toBeTruthy();
    for (const r of REASONS) expect(screen.getByText(r)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Recommended for you" })).toBeTruthy();
  });

  it("asks for the company profile when it is incomplete", async () => {
    mockFetch({ ...base, "GET /api/auth/me": SIGNED_IN, "GET /api/recommendations": page({ count: 0, results: [], profile_incomplete: true }) });
    renderPage(<RecommendedSection />);

    const cta = await screen.findByRole("link", { name: /Complete your company profile/ });
    expect(cta.getAttribute("href")).toBe("/workspace#profile");
    expect(screen.queryByText("Sector: Roads")).toBeNull();
  });

  it("the Explore tab lists them with reasons and the same call to action", async () => {
    mockFetch({ ...base, "GET /api/auth/me": SIGNED_IN, "GET /api/recommendations": page({ count: 0, results: [], profile_incomplete: true }) });
    renderPage(<RecommendedList page={1} onPage={() => {}} />);
    expect(await screen.findByRole("link", { name: /Complete your company profile/ })).toBeTruthy();
  });

  it("stays hidden, without asking the server, for visitors who aren't signed in", async () => {
    const calls = mockFetch({ ...base, "GET /api/auth/me": SIGNED_OUT, "GET /api/recommendations": page() });
    const { container } = renderPage(<RecommendedSection />);
    await waitFor(() => expect(calls.some((c) => c.url.startsWith("/api/auth/me"))).toBe(true));
    expect(container.textContent).toBe("");
    expect(calls.some((c) => c.url.startsWith("/api/recommendations"))).toBe(false);
  });
});
